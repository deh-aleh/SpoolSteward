"""Self-registration of local accounts: the public sign-up page, the switch administrators share, and their decision."""

import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from spoolsteward.admin.common import back, client_ip, current_admin, flash, get_db, render, session_stamp, verify_csrf
from spoolsteward.auth import passwords, registration
from spoolsteward.auth.throttle import Throttle
from spoolsteward.config import settings
from spoolsteward.db.models import User
from spoolsteward.i18n import _

log = logging.getLogger("spoolsteward.admin")
router = APIRouter(prefix="/admin")
public_router = APIRouter()   # /register: for people without an account, so no session and no CSRF token yet


def _throttle(app) -> Throttle:
    """Every use of the sign-up page counts, successful or not: it is the brake on spam and on guessing which names are taken."""
    if getattr(app.state, "register_throttle", None) is None:
        app.state.register_throttle = Throttle(limit=settings.register_per_ip_hour, window=3600)
    return app.state.register_throttle


def _int(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isascii() and text.isdigit() else None


# ------------------------------------------------------------------ the public page

@public_router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    with request.app.state.sessionmaker() as db:
        st = registration.state(db, datetime.now(UTC))
    if not st.is_open:
        return render(request, "register.html", status_code=404, closed=True, groups=[], approval=False)
    return render(request, "register.html", closed=False, groups=st.groups, approval=st.mode == "approval")


@public_router.post("/register")
async def register_submit(request: Request, username: str = Form(""), password: str = Form(""), confirm: str = Form(""),
                          group_id: str = Form("")):
    if request.url.scheme != "https" and not settings.allow_insecure_auth:
        raise HTTPException(403, "TLS required")
    throttle, ip = _throttle(request.app), client_ip(request)
    key = f"register|{ip}"
    if throttle.blocked(key):
        flash(request, _("Too many attempts, retry later"), "err")
        return back("/register")
    throttle.fail(key)
    now = datetime.now(UTC)

    def create() -> User:
        with request.app.state.sessionmaker() as db:
            user = registration.register(db, username, password, confirm, _int(group_id) or 0, ip, now)
            db.expunge(user)
            return user

    try:
        async with passwords.slot():
            user = await run_in_threadpool(create)
    except registration.Closed:
        return back("/register")
    except registration.RegistrationError as exc:
        flash(request, str(exc), "err")
        return back("/register")
    log.info("account %s registered itself from %s (%s)", user.username, ip, "active" if user.enabled else "waiting for an administrator")
    if not user.enabled:
        flash(request, _("Account created. It will be active when the system administrator enables it."))
        return back("/login")
    request.session.clear()
    request.session.update(uid=user.id, csrf=secrets.token_urlsafe(32), stamp=session_stamp(user), lang="")
    return back("/me")


# ------------------------------------------------------------------ administrators

@router.post("/registration", dependencies=[Depends(verify_csrf)])
def registration_set(request: Request, mode: str = Form("off"), hours: str = Form(""), accounts: str = Form(""),
                     admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    h, n = _int(hours), _int(accounts)
    try:
        if (hours.strip() and h is None) or (accounts.strip() and n is None):
            raise registration.RegistrationError(_("invalid request"))
        registration.configure(db, admin, mode, h, n, datetime.now(UTC))
        log.warning("admin %s set self-registration to %s", admin.username, mode)
        flash(request, _("Registration is now off") if mode == "off" else _("Registration is now open"))
    except registration.RegistrationError as exc:
        flash(request, str(exc), "err")
    return back("/admin/users")


@router.post("/registrations/{reg_id}/approve", dependencies=[Depends(verify_csrf)])
def registration_approve(request: Request, reg_id: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    try:
        user = registration.approve(db, reg_id, admin)
        flash(request, _("%(user)s can now log in", user=user.username))
    except registration.RegistrationError as exc:
        flash(request, str(exc), "err")
    return back("/admin/requests")


@router.post("/registrations/{reg_id}/reject", dependencies=[Depends(verify_csrf)])
def registration_reject(request: Request, reg_id: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    try:
        name = registration.reject(db, reg_id, admin)
        flash(request, _("Registration of %(user)s rejected: the account was deleted", user=name))
    except registration.RegistrationError as exc:
        flash(request, str(exc), "err")
    return back("/admin/requests")
