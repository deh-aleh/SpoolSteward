"""Shared pieces of the portal: templates, session/CSRF dependencies, helpers."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy.orm import Session
from babel.dates import format_date

from spoolsteward import i18n
from spoolsteward.admin.icons import ICONS
from spoolsteward.timeutil import aware, local_tz
from spoolsteward.auth.compare import same_text
from spoolsteward.backup.core import app_version, display_name
from spoolsteward.config import settings
from spoolsteward.i18n import N_
from spoolsteward.db.models import User
from spoolsteward.netutil import client_ip  # noqa: F401  (re-exported: the portal modules import it from here)
from spoolsteward.policy.permissions import describe_grant, describe_hours
from spoolsteward.policy.rules import MAX_LIMIT

templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def localtime(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:  # SQLite returns naive; we store UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(local_tz()).strftime(fmt)


def isotime(value: str | None) -> str:
    """localtime() for a timestamp that was stored as text (ISO 8601) inside a notice."""
    try:
        return localtime(datetime.fromisoformat(value)) if value else ""
    except ValueError:
        return ""


def _local_date(dt: datetime) -> datetime:
    if dt.tzinfo is None:  # SQLite returns naive; we store UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(local_tz())


def day_label(dt: datetime | None) -> str:
    """A day for people, in the language of the page: "Today", "Yesterday", "Monday 16 November" (the year only when it is not this one)."""
    if dt is None:
        return ""
    day, today = _local_date(dt).date(), datetime.now(local_tz()).date()
    if day == today:
        return i18n.gettext("Today")
    if (today - day).days == 1:
        return i18n.gettext("Yesterday")
    pattern = "EEEE d MMMM" if day.year == today.year else "EEEE d MMMM y"
    return format_date(day, pattern, locale=i18n.current())


def near_time(dt: datetime | None) -> str:
    """A moment close to now in words: "today at 19:25", "yesterday at 21:08", "Monday 16 November, 03:00"."""
    if dt is None:
        return ""
    local, today = _local_date(dt), datetime.now(local_tz()).date()
    clock = local.strftime("%H:%M")
    if local.date() == today:
        return i18n.gettext("today at %(time)s", time=clock)
    if (today - local.date()).days == 1:
        return i18n.gettext("yesterday at %(time)s", time=clock)
    return f"{day_label(dt)}, {clock}"


def next_day(dt: datetime | None) -> str:
    """A moment in the near future in words: "today at 05:08", "tomorrow at 05:08", then the date."""
    if dt is None:
        return ""
    local, today = _local_date(dt), datetime.now(local_tz()).date()
    clock = local.strftime("%H:%M")
    if local.date() == today:
        return i18n.gettext("today at %(time)s", time=clock)
    if (local.date() - today).days == 1:
        return i18n.gettext("tomorrow at %(time)s", time=clock)
    return f"{format_date(local.date(), 'EEEE d MMMM', locale=i18n.current())}, {clock}"


def full_day(dt: datetime | None) -> str:
    """A date in words, always ("Monday 16 November"; the year only when it is not this one): for what happens later."""
    if dt is None:
        return ""
    day = _local_date(dt).date()
    return format_date(day, "EEEE d MMMM" if day.year == datetime.now(local_tz()).year else "EEEE d MMMM y", locale=i18n.current())


def short_day(value) -> str:
    """"30 November" from a date or from "2026-11-30"."""
    if not value:
        return ""
    from datetime import date
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return format_date(day, "d MMMM" if day.year == datetime.now(local_tz()).year else "d MMMM y", locale=i18n.current())


def reset_day(dt: datetime | None, period: str = "weekly") -> str:
    """The day a quota starts again, for "until Monday" (weekly) or "until 1 December" (monthly)."""
    if dt is None:
        return ""
    day = _local_date(dt).date()
    return format_date(day, "EEEE" if period == "weekly" else "d MMMM", locale=i18n.current())


# The words for states. A state is stored in English ("accepted"); the page says it in the reader's language, with a capital letter
# (the stylesheet does that). Listed here so the catalogs keep them: a template that writes _(state) would not be found by the extractor.
WORDS = {
    "accepted": N_("accepted"), "completed": N_("completed"), "denied": N_("denied"), "failed": N_("failed"), "canceled": N_("canceled"),
    "held": N_("on hold"), "pending": N_("pending"), "approved": N_("approved"), "rejected": N_("rejected"), "expired": N_("expired"),
    "revoked": N_("revoked"), "ended": N_("ended"), "active": N_("active"), "disabled": N_("disabled"),
}


def state_word(value: str) -> str:
    return i18n.gettext(WORDS[value]) if value in WORDS else i18n.gettext(value)


def icon(name: str, cls: str = "") -> Markup:
    """An inline Tabler icon (see icons.py). An unknown name is a bug in a template: it fails loudly in the tests."""
    return Markup('<svg class="ic%s" viewBox="0 0 24 24" aria-hidden="true">%s</svg>') % (" " + cls if cls else "", Markup(ICONS[name]))


templates.env.filters["localtime"] = localtime
templates.env.filters["isotime"] = isotime
templates.env.filters["day"] = day_label
templates.env.filters["neartime"] = near_time
templates.env.filters["nextday"] = next_day
templates.env.filters["fullday"] = full_day
templates.env.filters["shortday"] = short_day
templates.env.filters["resetday"] = reset_day
templates.env.globals["icon"] = icon
templates.env.globals["state_word"] = state_word
templates.env.globals["backup_name"] = display_name
templates.env.globals.update(_=i18n.html_gettext, _p=i18n.html_pgettext, _t=i18n.plain_gettext, _js=i18n.raw_gettext, ngettext=i18n.html_ngettext, lang=i18n.current, languages=i18n.LANGUAGES,
                            hours_text=describe_hours, perm_text=describe_grant, password_min_length=settings.password_min_length)


def get_db(request: Request):
    with request.app.state.sessionmaker() as session:
        yield session


def session_stamp(user: User) -> str:
    """Changes whenever the password changes, which ends every other session of that user."""
    dt = user.password_changed_at
    if dt is None:
        return ""
    # SQLite hands datetimes back without tzinfo; we store UTC, so both forms must give the same stamp
    return aware(dt).astimezone(UTC).isoformat()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or not user.enabled or request.session.get("stamp", "") != session_stamp(user):
        request.session.clear()
        raise HTTPException(303, headers={"Location": "/login"})
    if request.session.get("lang") != (user.language or ""):  # chosen on another device since this session started
        request.session["lang"] = user.language or ""
    if user.must_change_password and request.url.path != "/me/password":
        raise HTTPException(303, headers={"Location": "/me/password"})
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "administrators only")
    return user


def check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not same_text(token, expected):
        raise HTTPException(403, "invalid CSRF token")


async def verify_csrf(request: Request, csrf_token: str = Form("")) -> None:
    check_csrf(request, csrf_token)


def flash(request: Request, msg: str, kind: str = "ok") -> None:
    # reassign: Starlette only notices changes to top-level keys, not in-place list mutation
    request.session["flash"] = [*request.session.get("flash", []), [kind, msg]]


def render(request: Request, name: str, user: User | None = None, status_code: int = 200, **ctx) -> HTMLResponse:
    if user is not None:
        from spoolsteward import notices

        notices.read_secondary(request.app.state.sessionmaker, user.id, user.secondary_read_minutes)
    ctx.update(me=user, csrf=request.session.get("csrf", ""), flashes=request.session.pop("flash", []),
               radius_enabled=settings.radius_enabled,
               pending_requests=_pending_requests(request) if user is not None and user.is_admin else 0,
               notices_unseen=_notices_unseen(request, user.id) if user is not None and user.is_admin else 0,
               own_unseen=_notices_unseen(request, user.id, own=True) if user is not None else 0,
               maintenance=_maintenance(request) if user is not None else False,
               update_info=getattr(request.app.state, "update_info", None) if user is not None and user.is_admin else None,
               app_version=app_version())
    resp = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    resp.headers["Cache-Control"] = "no-store"  # pages may carry one-time secrets (new keys, temporary passwords)
    return resp


def _pending_requests(request: Request) -> int:
    from sqlalchemy import func, select

    from spoolsteward.auth import registration
    from spoolsteward.db.models import QuotaRequest, RequestStatus

    now = datetime.now(UTC)
    with request.app.state.sessionmaker() as db:
        return (db.scalar(select(func.count(QuotaRequest.id)).where(
            QuotaRequest.status == RequestStatus.pending, QuotaRequest.expires_at > now)) or 0) + registration.count_pending(db, now)


def _notices_unseen(request: Request, user_id: int, own: bool = False) -> int:
    from spoolsteward import notices

    return notices.unseen_count(request.app.state.sessionmaker, user_id, own=own)


def _maintenance(request: Request) -> bool:
    from spoolsteward.policy.control import is_maintenance

    with request.app.state.sessionmaker() as db:
        return is_maintenance(db)


def safe_next(path: str, default: str) -> str:
    """Where to go after a form: only paths of this site (no open redirect)."""
    return path if path.startswith("/") and not path.startswith("//") and "\\" not in path else default


def back(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def parse_limit(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if not (raw.isascii() and raw.isdigit()):
        raise ValueError(i18n.gettext("invalid limit %(value)s", value=repr(raw)))
    value = int(raw)
    if value > MAX_LIMIT:
        raise ValueError(i18n.gettext("limit too large (max %(max)s)", max=MAX_LIMIT))
    return value


