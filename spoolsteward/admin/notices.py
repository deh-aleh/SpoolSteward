"""The bell: notices for administrators (things the gateway noticed and nobody asked about)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spoolsteward import notices
from spoolsteward.admin.common import _notices_unseen as _unseen, back, current_admin, flash, get_db, render, verify_csrf
from spoolsteward.audit.adminlog import record
from spoolsteward.db.models import Notice, User
from spoolsteward.i18n import _, ngettext

router = APIRouter(prefix="/admin/notices")


def _every(seconds: int) -> str:
    if seconds < 3600:
        return ngettext("%(n)s minute", "%(n)s minutes", max(seconds // 60, 1))
    if seconds < 86400:
        return ngettext("%(n)s hour", "%(n)s hours", seconds // 3600)
    return ngettext("%(n)s day", "%(n)s days", seconds // 86400)


@router.get("", response_class=HTMLResponse)
def listing(request: Request, all: int = 0, tab: str = "", admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Two tabs, one bell: what concerns the administrator's own account ("own") and what the gateway noticed ("gateway")."""
    if tab not in ("own", "gateway"):   # no tab asked: the one with something new (the gateway's, unless only the own ones are)
        tab = "own" if _unseen(request, admin.id, own=True) and not _unseen(request, admin.id) else "gateway"
    now = datetime.now(UTC)
    unseen_own = db.scalar(select(func.count()).select_from(Notice).where(Notice.user_id == admin.id, Notice.dismissed_at.is_(None))) or 0
    if tab == "own":
        q = select(Notice).where(Notice.user_id == admin.id).order_by(Notice.last_at.desc())   # the administrator's own notices share the bell
        admin.own_notices_seen_at = now   # opening the list is what "seeing" them means: the red dot goes away
    else:
        q = select(Notice).where(Notice.user_id.is_(None)).order_by(Notice.last_at.desc())
        admin.notices_seen_at = now
    if not all:
        q = q.where(Notice.dismissed_at.is_(None))
    db.commit()
    found = list(db.scalars(q.limit(200)))
    if tab == "own":
        return render(request, "notices.html", admin, tab="own", own_rows=found, rows=[], show_all=bool(all), when="",
                      own_base="/admin/notices?tab=own", own_base_q="&", own_open=unseen_own)
    rows = [{"n": n, "extra": notices.pending(n.kind, n.key) if n.dismissed_at is None else 0} for n in found]
    return render(request, "notices.html", admin, tab="gateway", rows=rows, own_rows=[], show_all=bool(all), when=_every(notices.interval()))


@router.post("/{nid}/dismiss", dependencies=[Depends(verify_csrf)])
def dismiss(request: Request, nid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    n = db.get(Notice, nid)
    if n is None or n.user_id is not None:
        raise HTTPException(404)
    if n.dismissed_at is None:
        n.dismissed_at, n.dismissed_by = datetime.now(UTC), admin.username
        record(db, admin, "notice.dismiss", "notice", n.id, kind=n.kind, source=n.key)
        db.commit()
    return back("/admin/notices")


@router.post("/dismiss-all", dependencies=[Depends(verify_csrf)])
def dismiss_all(request: Request, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    now, done = datetime.now(UTC), 0
    for n in db.scalars(select(Notice).where(Notice.dismissed_at.is_(None), Notice.user_id.is_(None))):
        n.dismissed_at, n.dismissed_by = now, admin.username
        done += 1
    if done:
        record(db, admin, "notice.dismiss_all", "notice", 0, count=done)
        db.commit()
    flash(request, _("%(n)s notices dismissed", n=done))
    return back("/admin/notices")
