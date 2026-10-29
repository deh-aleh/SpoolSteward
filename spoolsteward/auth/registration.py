"""Self-registration of local accounts: the switch shared by every administrator, the public sign-up and the decision.

The switch lives in `gateway_setting` (one state for all administrators). Its end (a time and/or a number of accounts)
is checked when somebody registers, never by a timer, so it also holds across a restart. A person who registers always
gets a local account in a group an administrator marked `requestable`: never an administrator, never another group.
In "approval" mode the account is created disabled with a `registration` row, and an administrator approves or rejects it;
rejecting (or letting it expire) deletes the account, which never did anything.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Integer, String, cast, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from spoolsteward.audit.adminlog import record
from spoolsteward.auth.groups import ADMIN_GROUP
from spoolsteward.auth.passwords import hash_password, validate_new_password
from spoolsteward.auth.users import delete_user
from spoolsteward.config import USERNAME_RE, settings
from spoolsteward.db.models import GatewaySetting, Group, Registration, User
from spoolsteward.i18n import _
from spoolsteward.timeutil import aware

MODE, UNTIL, LEFT = "registration_mode", "registration_until", "registration_left"
MODES = ("off", "open", "approval")
MAX_HOURS = 24 * 365
MAX_ACCOUNTS = 10_000
ACTOR = "registration"   # who the audit shows for what a not-yet-logged-in person did


class RegistrationError(ValueError):
    """Something the person (or the administrator) did that can not be accepted; the message is safe to show."""


class Closed(RegistrationError):
    """Registration is not open (any more)."""


@dataclass
class State:
    mode: str                 # off | open | approval: what an administrator chose
    until: datetime | None    # end of the opening, None = until switched off
    left: int | None          # accounts still allowed, None = no limit
    groups: list[Group]       # where a new person may go
    closed: str | None        # why it is closed: off | expired | no_groups; None = open

    @property
    def is_open(self) -> bool:
        return self.closed is None


def _get(db: Session, key: str) -> str:
    row = db.get(GatewaySetting, key)
    return row.value if row else ""


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(GatewaySetting, key)
    if row is None:
        db.add(GatewaySetting(key=key, value=value))
    else:
        row.value = value


def requestable_groups(db: Session) -> list[Group]:
    return list(db.scalars(select(Group).where(Group.requestable.is_(True), Group.name != ADMIN_GROUP).order_by(Group.name)))


def state(db: Session, now: datetime) -> State:
    mode = _get(db, MODE)
    mode = mode if mode in MODES else "off"
    try:
        until = datetime.fromisoformat(_get(db, UNTIL)) if _get(db, UNTIL) else None
    except ValueError:
        until = None
    left = int(_get(db, LEFT)) if _get(db, LEFT).isdigit() else None
    groups = requestable_groups(db)
    closed = ("off" if mode == "off" else "expired" if until is not None and aware(until) <= now
              else "no_groups" if not groups else None)
    return State(mode, until, left, groups, closed)


def is_open(db: Session, now: datetime) -> bool:
    return state(db, now).is_open


def configure(db: Session, admin: User, mode: str, hours: int | None, accounts: int | None, now: datetime) -> None:
    """Switch registration off, or on in a mode, for `hours` and/or for `accounts` people (None = no end of that kind)."""
    if mode not in MODES:
        raise RegistrationError(_("invalid request"))
    if mode == "off":
        _set(db, MODE, "off")
        _set(db, UNTIL, "")
        _set(db, LEFT, "")
        record(db, admin, "registration.close", "gateway", None)
        db.commit()
        return
    if hours is not None and not 1 <= hours <= MAX_HOURS:
        raise RegistrationError(_("invalid request"))
    if accounts is not None and not 1 <= accounts <= MAX_ACCOUNTS:
        raise RegistrationError(_("the number of accounts must be between 1 and %(max)s", max=MAX_ACCOUNTS))
    if not requestable_groups(db):
        raise RegistrationError(_("no group can be requested: mark at least one group as requestable first"))
    until = now + timedelta(hours=hours) if hours is not None else None
    _set(db, MODE, mode)
    _set(db, UNTIL, until.isoformat() if until else "")
    _set(db, LEFT, str(accounts) if accounts is not None else "")
    record(db, admin, "registration.open", "gateway", None, mode=mode, until=until.isoformat() if until else None, accounts=accounts)
    db.commit()


def _consume(db: Session) -> bool:
    """One account less of the limit, decided by the database alone (two people at once can not both take the last place).
    True when there is no limit, or a place was taken."""
    if not _get(db, LEFT):
        return True
    n = cast(GatewaySetting.value, Integer)
    taken = db.execute(update(GatewaySetting).where(GatewaySetting.key == LEFT, n > 0)
                       .values(value=cast(n - 1, String)).execution_options(synchronize_session=False)).rowcount
    return taken == 1


def register(db: Session, username: str, password: str, confirm: str, group_id: int, ip: str, now: datetime) -> User:
    """Create the account of a person who asked for it. Commits. Raises Closed / RegistrationError."""
    st = state(db, now)
    if not st.is_open:
        raise Closed(_("Registration is closed"))
    name = username.strip().lower()
    if not USERNAME_RE.match(name):
        raise RegistrationError(_("Invalid username (letters, digits, dot, dash, underscore; max 63)"))
    if name == settings.bootstrap_admin_username or db.scalars(select(User).where(User.username == name)).first():
        raise RegistrationError(_("The name %(name)s is not available", name=name))
    if group_id not in {g.id for g in st.groups}:
        raise RegistrationError(_("Choose one of the groups"))
    if password != confirm:
        raise RegistrationError(_("the two passwords differ"))
    error = validate_new_password(password, name)
    if error:
        raise RegistrationError(error)
    pending = st.mode == "approval"
    try:
        if not _consume(db):
            db.rollback()
            raise Closed(_("Registration is closed"))
        user = User(provider="local", username=name, group_id=group_id, password_hash=hash_password(password),
                    enabled=not pending, must_change_password=False, password_changed_at=now)
        db.add(user)
        db.flush()
        if pending:
            db.add(Registration(user_id=user.id, created_at=now, expires_at=now + timedelta(days=settings.request_ttl_days), ip=ip[:64]))
        if db.scalar(select(GatewaySetting.value).where(GatewaySetting.key == LEFT)) == "0":   # that was the last place
            _set(db, MODE, "off")
            _set(db, UNTIL, "")
            _set(db, LEFT, "")
            record(db, None, "registration.close", "gateway", None, actor_name=ACTOR, reason="limit reached")
        record(db, None, "registration.create", "user", user.id, actor_name=ACTOR, username=name, group_id=group_id,
               pending=pending, ip=ip)
        db.commit()
    except IntegrityError:   # somebody took the name a moment ago
        db.rollback()
        raise RegistrationError(_("The name %(name)s is not available", name=name)) from None
    return user


def pending(db: Session, now: datetime) -> list[dict]:
    """The accounts waiting for a decision: [{"reg", "user", "group"}], oldest first."""
    groups = {g.id: g.name for g in db.scalars(select(Group))}
    rows = db.execute(select(Registration, User).join(User, User.id == Registration.user_id)
                      .where(Registration.expires_at > now, User.enabled.is_(False)).order_by(Registration.id)).all()
    return [{"reg": r, "user": u, "group": groups.get(u.group_id, "—")} for r, u in rows]


def count_pending(db: Session, now: datetime) -> int:
    return db.scalar(select(func.count(Registration.id)).join(User, User.id == Registration.user_id)
                     .where(Registration.expires_at > now, User.enabled.is_(False))) or 0


def _claim(db: Session, reg_id: int) -> User:
    """Take the registration for ourselves (a conditional DELETE: two administrators can not both decide)."""
    reg = db.get(Registration, reg_id)
    user = db.get(User, reg.user_id) if reg is not None else None
    if reg is None or user is None:
        raise RegistrationError(_("the request was already decided"))
    if db.execute(delete(Registration).where(Registration.id == reg_id)).rowcount != 1:
        db.rollback()
        raise RegistrationError(_("the request was already decided"))
    return user


def approve(db: Session, reg_id: int, admin: User) -> User:
    user = _claim(db, reg_id)
    user.enabled = True
    record(db, admin, "registration.approve", "user", user.id, username=user.username)
    db.commit()
    return user


def reject(db: Session, reg_id: int, admin: User) -> str:
    """Delete the account. Only ever an account that is still disabled and ordinary: one an administrator already enabled
    keeps existing (its pending mark is just dropped)."""
    user = _claim(db, reg_id)
    if user.enabled or user.is_admin:
        db.commit()
        raise RegistrationError(_("%(user)s is already active: delete the account from its page if you want it gone", user=user.username))
    name = user.username
    delete_user(db, user)
    record(db, admin, "registration.reject", "user", None, username=name)
    db.commit()
    return name


def expire(db: Session, now: datetime) -> int:
    """Forget the registrations nobody decided in time (the account is deleted), and the marks left by accounts that were
    enabled or deleted in the meantime. Returns how many accounts were deleted."""
    stale = [r for r, u in db.execute(select(Registration, User).outerjoin(User, User.id == Registration.user_id)).all()
             if u is None or u.enabled or u.is_admin]
    for r in stale:
        db.execute(delete(Registration).where(Registration.id == r.id))
    gone = 0
    for r in db.scalars(select(Registration).where(Registration.expires_at <= now)).all():
        user = db.get(User, r.user_id)
        if db.execute(delete(Registration).where(Registration.id == r.id)).rowcount != 1 or user is None:
            continue
        name = user.username
        delete_user(db, user)
        record(db, None, "registration.expire", "user", None, actor_name=ACTOR, username=name)
        gone += 1
    db.commit()
    return gone

