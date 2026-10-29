"""Audit retention: kept forever, moved to compressed files when the active tables get heavy.

Nothing in the application deletes audit rows except this module, and only AFTER the same rows are safely in a
verified compressed file that is listed in `audit_archive`. The portal can read and download archives, never
remove them. Rows of the quota windows still in play are never archived, so limits are not affected.

Crash safety, in order:
  1. write <file>.pending (fsync) and re-read it to verify
  2. ONE transaction: register the archive + delete the archived rows
  3. rename <file>.pending -> <file>, make it read-only
A crash after 1 leaves a stray .pending file whose rows are still in the database (removed next run); a crash
after 2 leaves a registry entry whose file is still named .pending (renamed next run).
"""

import gzip
import json
import logging
import os
import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, delete, func, select
from starlette.concurrency import run_in_threadpool

from spoolsteward import crypto_fields, titles
from spoolsteward.timeutil import aware, local_tz
from spoolsteward.audit.adminlog import record
from spoolsteward.config import settings
from spoolsteward.db.models import AdminAudit, AuditArchive, JobLog, User
from spoolsteward.fileutil import sha256_file

log = logging.getLogger(__name__)
TABLES = {"job_log": JobLog, "admin_audit": AdminAudit}


class ArchiveError(RuntimeError):
    pass


@dataclass
class ArchiveResult:
    table: str
    path: Path
    rows: int
    bytes: int
    sha256: str


BATCH_ROWS = 5000        # rows held in memory at once while an archive is written
SAMPLE_ROWS = 500        # newest rows measured to estimate the average weight of a row


def _row_weight(table: str):
    L = lambda col: func.length(func.coalesce(col, ""))  # noqa: E731
    if table == "job_log":
        return 64 + L(JobLog.title) + L(JobLog.printer) + L(JobLog.denied_reason) + L(cast(JobLog.options_json, String))
    return 64 + L(AdminAudit.action) + L(AdminAudit.target_type) + L(AdminAudit.actor_name) \
        + L(cast(AdminAudit.detail_json, String))


def estimate_bytes(db, table: str) -> int:
    """Rough size of the active table's data: enough to decide when it is 'heavy'. It counts the rows and
    measures only the newest SAMPLE_ROWS of them (a table with fewer rows is measured exactly), so it stays cheap
    on a slow SD card however big the table gets."""
    model = TABLES[table]
    rows = db.scalar(select(func.count(model.id))) or 0
    if rows <= SAMPLE_ROWS:
        return db.scalar(select(func.coalesce(func.sum(_row_weight(table)), 0))) or 0
    newest = select(_row_weight(table).label("w")).order_by(model.id.desc()).limit(SAMPLE_ROWS).subquery()
    average = (db.scalar(select(func.coalesce(func.sum(newest.c.w), 0))) or 0) / SAMPLE_ROWS
    return int(average * rows)


def protected_from(now: datetime, tz: ZoneInfo) -> datetime:
    """Rows from here on are never archived: the previous calendar month plus the current one cover every
    weekly/monthly quota window that can still matter."""
    local = now.astimezone(tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = local.replace(year=local.year - (local.month == 1), month=(local.month - 2) % 12 + 1)
    return prev.astimezone(UTC)


def _jsonable(v):
    return aware(v).isoformat() if isinstance(v, datetime) else getattr(v, "value", v)


def _row_dict(table: str, obj, usernames: dict[int, str]) -> dict:
    if table == "job_log":
        title, options = obj.title, obj.options_json
        cut = titles.cutoff_for_archive()
        if cut is not None and aware(obj.ts) < cut:  # past the retention: the name does not go into the file
            title, options = None, {k: v for k, v in (options or {}).items() if k != "document_name"} or None
        else:  # the file keeps the names encrypted, like the database (the portal decrypts them when it shows them)
            title = crypto_fields.seal(title)
            if options and isinstance(options.get("document_name"), str):
                options = {**options, "document_name": crypto_fields.seal(options["document_name"])}
        return {
            "id": obj.id, "ts": _jsonable(obj.ts), "user_id": obj.user_id, "user": usernames.get(obj.user_id) or obj.user_name,
            "kind": _jsonable(obj.kind), "printer": obj.printer, "cups_job_id": obj.cups_job_id, "title": title,
            "pages": obj.pages, "state": _jsonable(obj.state), "reason": obj.denied_reason, "options": options,
        }
    return {
        "id": obj.id, "ts": _jsonable(obj.ts), "actor_id": obj.actor_id, "actor": obj.actor_name,
        "action": obj.action, "target_type": obj.target_type, "target_id": obj.target_id, "detail": obj.detail_json,
    }


def _final_path(directory: Path, table: str, first_id: int, last_id: int) -> Path:
    return directory / f"audit-{table}-{first_id:09d}-{last_id:09d}.jsonl.gz"


def _write_pending(pending: Path, table: str, rows: Iterator, usernames: dict[int, str]) -> tuple[int, str, int]:
    """Deterministic gzip (mtime 0): writing the same rows twice gives the same bytes. `rows` is read once,
    row by row. Returns (bytes, sha256, rows written)."""
    written = 0
    with open(pending, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=6) as gz:
            for obj in rows:
                gz.write((json.dumps(_row_dict(table, obj, usernames), ensure_ascii=False, separators=(",", ":"))
                          + "\n").encode("utf-8"))
                written += 1
        raw.flush()
        os.fsync(raw.fileno())
    return pending.stat().st_size, sha256_file(pending), written


def count_lines(path: Path) -> int:
    with gzip.open(path, "rb") as f:
        return sum(1 for _ in f)


def _same_rows(db, model, path: Path, where, last_id: int) -> bool:
    """True if the file holds exactly the rows the database would archive now (same ids, same order). Both are streamed."""
    mine = iter(db.scalars(select(model.id).where(*where, model.id <= last_id).order_by(model.id)
                           .execution_options(yield_per=BATCH_ROWS)))
    try:
        for row in iter_archive(path):
            if row.get("id") != next(mine, None):
                return False
    except (OSError, EOFError, ValueError):  # not a gzip file, cut short, not JSON: it is not what we wanted
        return False
    return next(mine, None) is None


def repair(sm, directory: Path) -> None:
    """Finish or clean up after a crash (see the module docstring)."""
    if not directory.is_dir():
        return
    with sm() as db:
        registered = {Path(a.path) for a in db.scalars(select(AuditArchive))}
    for path in registered:
        pending = path.with_name(path.name + ".pending")
        if not path.exists() and pending.exists():
            os.replace(pending, path)
            os.chmod(path, 0o444)
            log.warning("audit archive: finished an interrupted rename of %s", path.name)
    for stray in directory.glob("audit-*.jsonl.gz.pending"):
        if Path(str(stray)[: -len(".pending")]) not in registered:
            stray.unlink()  # crash before the commit: its rows are still in the database
            log.warning("audit archive: removed unfinished file %s", stray.name)


def archive_table(sm, table: str, now: datetime, tz: ZoneInfo, directory: Path, max_bytes: int,
                  force: bool = False) -> ArchiveResult | None:
    model = TABLES[table]
    directory.mkdir(parents=True, exist_ok=True)
    repair(sm, directory)
    cutoff = protected_from(now, tz)
    old = (model.ts < cutoff,)
    # Reading and writing use two sessions: the rows are streamed to the file with no database transaction held
    # open for minutes, and the delete below only has to match what the first pass saw.
    with sm() as db:
        if not force and estimate_bytes(db, table) <= max_bytes:
            return None
        total, first_id, last_id = db.execute(select(func.count(model.id), func.min(model.id), func.max(model.id))
                                              .where(*old)).one()
        if not total:
            log.info("audit archive: %s is over the threshold but everything is inside the protected window", table)
            return None
        first_ts, last_ts = (aware(db.get(model, i).ts) for i in (first_id, last_id))
        usernames = {u.id: u.username for u in db.scalars(select(User))}
        final = _final_path(directory, table, first_id, last_id)
        if db.scalars(select(AuditArchive).where(AuditArchive.source_table == table, AuditArchive.first_id == first_id,
                                                 AuditArchive.last_id == last_id)).first():
            raise ArchiveError(f"{final.name} is already registered: refusing to archive the same rows twice")
        adopted = False
        if final.exists():
            # A file of this name that the registry does not know: an older backup of the database was restored while the
            # file stayed. Same rows: it is that file, register it as it is. Anything else: put it aside, never overwrite it.
            adopted = _same_rows(db, model, final, old, last_id)
            if adopted:
                log.warning("audit archive: %s already holds these rows, registered as it is", final.name)
                size, digest, written = final.stat().st_size, sha256_file(final), total
            else:
                aside = final.with_name(f"{final.name}.old-{now:%Y%m%d%H%M%S}")
                os.replace(final, aside)
                log.warning("audit archive: %s did not match the database, kept as %s", final.name, aside.name)
        pending = final.with_name(final.name + ".pending")
        if not adopted:
            stream = db.scalars(select(model).where(*old, model.id <= last_id).order_by(model.id)
                                .execution_options(yield_per=BATCH_ROWS))
            size, digest, written = _write_pending(pending, table, stream, usernames)
    if not adopted and (written != total or count_lines(pending) != total):  # verify what is on disk, not what we think we wrote
        pending.unlink()
        raise ArchiveError("verification failed: line count differs, nothing was removed")
    with sm() as db:
        db.add(AuditArchive(source_table=table, path=str(final), first_ts=first_ts, last_ts=last_ts,
                            first_id=first_id, last_id=last_id, rows=total, bytes=size, sha256=digest,
                            created_at=now))
        gone = db.execute(delete(model).where(*old, model.id.between(first_id, last_id))).rowcount
        if gone != total:  # the rows changed while the file was written: keep them, the file is dropped
            db.rollback()
            if not adopted:
                pending.unlink()
            raise ArchiveError(f"{gone} rows to remove but {total} archived: nothing was removed")
        record(db, None, "audit.archive", table, None, file=final.name, rows=total, bytes=size, sha256=digest,
               first_id=first_id, last_id=last_id)
        db.commit()
    if not adopted:
        os.replace(pending, final)
    os.chmod(final, 0o444)
    log.info("audit archive: %d rows of %s -> %s (%d bytes)", total, table, final, size)
    return ArchiveResult(table, final, total, size, digest)


def archive_all(sm, now: datetime | None = None, force: bool = False) -> list[ArchiveResult]:
    now = now or datetime.now(UTC)
    tz = local_tz()
    out = []
    for table in TABLES:
        try:
            res = archive_table(sm, table, now, tz, Path(settings.audit_archive_dir),
                                0 if force else settings.audit_max_mb << 20, force)
        except (OSError, ArchiveError):
            log.exception("audit archive of %s failed (nothing was removed)", table)
            continue
        if res:
            out.append(res)
    return out


# ---------------------------------------------------------------- reading (portal)

def archive_status(a: AuditArchive, verify: bool = False) -> str:
    path = Path(a.path)
    if not path.exists():
        return "missing"
    if path.stat().st_size != a.bytes:
        return "modified"
    if verify and sha256_file(path) != a.sha256:
        return "modified"
    return "ok" if verify else "present"


def _unsealed(row: dict) -> dict:
    """A line of an archive file with the encrypted file names opened (the file itself keeps them encrypted)."""
    if crypto_fields.is_sealed(row.get("title")):
        row["title"] = crypto_fields.unseal(row["title"])
    opts = row.get("options")
    if isinstance(opts, dict) and crypto_fields.is_sealed(opts.get("document_name")):
        opts["document_name"] = crypto_fields.unseal(opts["document_name"])
    return row


def iter_archive(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield _unsealed(json.loads(line))


def _rename(row: dict, names: dict[int, str]) -> None:
    """The user's name as it is now (a renamed account): the file keeps the name of the day it was written, with the user id."""
    if row.get("user_id") in names:
        row["user"] = names[row["user_id"]]


def read_page(path: Path, page: int, per_page: int, query: str = "",
              names: dict[int, str] | None = None) -> tuple[list[dict], int]:
    """(rows of one page, total matching rows), streaming the file. `names` (user id -> current name) replaces the stored
    name of the accounts that still exist, so a search finds the new name."""
    q = query.strip().lower()
    start, end, total, out = (page - 1) * per_page, page * per_page, 0, []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            row = None
            if crypto_fields.PREFIX in line or (names and q):  # search in the names as people read them, not as they are stored
                row = _unsealed(json.loads(line))
                if names:
                    _rename(row, names)
                line = json.dumps(row, ensure_ascii=False)
            if q and q not in line.lower():
                continue
            if start <= total < end:
                if row is None:
                    row = json.loads(line)
                    if names:
                        _rename(row, names)
                out.append(row)
            total += 1
    return out, total


async def run_archiver(app) -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await run_in_threadpool(archive_all, app.state.sessionmaker)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("audit archiver failed")
        await asyncio.sleep(settings.audit_check_interval)
