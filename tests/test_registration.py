"""Self-registration of local accounts: the shared switch, the public page, approval, expiry."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from spoolsteward.auth import registration
from spoolsteward.config import settings
from spoolsteward.db.models import AdminAudit, Group, Registration, User
from tests.conftest import GOOD, csrf_of_page, make_user, portal_login, user_row

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
async def reg(admin):
    """An administrator logged in, a requestable group 'guests' and a group nobody can ask for."""
    admin.app.state.register_throttle = None
    with admin.sm() as s:
        s.add(Group(name="guests", requestable=True))
        s.add(Group(name="staff", requestable=False))
        s.commit()
        admin.gid = s.scalars(select(Group).where(Group.name == "guests").limit(1)).one().id
        admin.staff = s.scalars(select(Group).where(Group.name == "staff").limit(1)).one().id
    return admin


async def turn_on(cl, mode="open", hours="", accounts=""):
    return await cl.post("/admin/registration", data={"csrf_token": await csrf_of_page(cl, "/admin/users"), "mode": mode,
                                                      "hours": hours, "accounts": accounts})


async def sign_up(cl, name="newbie", pw=GOOD, confirm=None, group=None):
    return await cl.post("/register", data={"username": name, "password": pw, "confirm": pw if confirm is None else confirm,
                                            "group_id": str(cl.gid if group is None else group)})


def audit_actions(cl):
    with cl.sm() as s:
        return [a.action for a in s.scalars(select(AdminAudit).order_by(AdminAudit.id))]


async def test_closed_by_default_and_the_login_page_has_no_link(portal):
    assert (await portal.get("/register")).status_code == 404
    assert (await portal.post("/register", data={"username": "x", "password": GOOD, "confirm": GOOD, "group_id": "1"})).status_code == 303
    assert user_row(portal, "x") is None
    assert "/register" not in (await portal.get("/login")).text


async def test_open_mode_creates_an_active_account_and_logs_it_in(reg):
    assert (await turn_on(reg)).status_code == 303
    assert 'href="/register"' in (await reg.get("/login")).text
    page = await reg.get("/register")
    assert page.status_code == 200 and "guests" in page.text and "staff" not in page.text
    r = await sign_up(reg)
    assert r.status_code == 303 and r.headers["location"] == "/me"
    assert (await reg.get("/me")).status_code == 200                                      # really logged in
    u = user_row(reg, "newbie")
    assert u.provider == "local" and u.enabled and not u.is_admin and not u.must_change_password and u.group_id == reg.gid
    assert "registration.create" in audit_actions(reg)
    with reg.sm() as s:
        assert s.scalar(select(func.count(Registration.id))) == 0


async def test_approval_mode_creates_a_disabled_account_that_an_administrator_decides(reg):
    await turn_on(reg, "approval")
    r = await sign_up(reg, "maria")
    assert r.headers["location"] == "/login"
    assert "active when the system administrator" in (await reg.get("/login")).text
    assert not user_row(reg, "maria").enabled
    assert (await portal_login(reg, "maria", GOOD)).headers["location"] == "/login"     # still "invalid credentials"
    with reg.sm() as s:
        rid = s.scalars(select(Registration)).one().id
    assert "Registrations waiting" in (await reg.get("/admin/requests")).text
    tok = await csrf_of_page(reg, "/admin/users")
    await reg.post(f"/admin/registrations/{rid}/approve", data={"csrf_token": tok})
    assert user_row(reg, "maria").enabled
    with reg.sm() as s:
        assert s.scalar(select(func.count(Registration.id))) == 0
    again = await reg.post(f"/admin/registrations/{rid}/approve", data={"csrf_token": tok})
    assert again.status_code == 303                                                       # already decided: a message, not a crash


async def test_rejecting_deletes_the_account(reg):
    await turn_on(reg, "approval")
    await sign_up(reg, "maria")
    with reg.sm() as s:
        rid = s.scalars(select(Registration)).one().id
    await reg.post(f"/admin/registrations/{rid}/reject", data={"csrf_token": await csrf_of_page(reg, "/admin/users")})
    assert user_row(reg, "maria") is None
    assert "registration.reject" in audit_actions(reg)


async def test_rejecting_never_deletes_an_account_that_is_already_active(reg):
    await turn_on(reg, "approval")
    await sign_up(reg, "maria")
    with reg.sm() as s:
        rid = s.scalars(select(Registration)).one().id
        s.scalars(select(User).where(User.username == "maria")).one().enabled = True    # enabled by hand from the user page
        s.commit()
    await reg.post(f"/admin/registrations/{rid}/reject", data={"csrf_token": await csrf_of_page(reg, "/admin/users")})
    assert user_row(reg, "maria") is not None


async def test_unpaid_wait_expires_and_deletes_only_the_waiting_account(reg):
    await turn_on(reg, "approval")
    await sign_up(reg, "maria")
    make_user(reg.sm, "old", password=GOOD)
    with reg.sm() as s:
        assert registration.expire(s, datetime.now(UTC)) == 0
        assert registration.expire(s, datetime.now(UTC) + timedelta(days=settings.request_ttl_days + 1)) == 1
    assert user_row(reg, "maria") is None and user_row(reg, "old") is not None


async def test_only_requestable_groups_and_never_administrator(reg):
    await turn_on(reg)
    for gid in (reg.staff, 0, 99999):
        r = await sign_up(reg, "sneaky", group=gid)
        assert r.headers["location"] == "/register" and user_row(reg, "sneaky") is None
    with reg.sm() as s:
        admins = s.scalars(select(Group).where(Group.name == "administrator")).one()
        admins.requestable = True            # even if marked by mistake
        s.commit()
        aid = admins.id
    await sign_up(reg, "sneaky", group=aid)
    assert user_row(reg, "sneaky") is None


async def test_names_passwords_and_duplicates_are_refused(reg):
    await turn_on(reg)
    make_user(reg.sm, "taken", password=GOOD)
    await sign_up(reg, "taken")
    await sign_up(reg, settings.bootstrap_admin_username)
    await sign_up(reg, "Bad Name!")
    await sign_up(reg, "shorty", pw="short", confirm="short")
    await sign_up(reg, "mismatch", confirm="another one entirely")
    with reg.sm() as s:
        assert [u.username for u in s.scalars(select(User).order_by(User.username))] == ["boss", "taken"]


async def test_the_limit_of_accounts_closes_registration_at_the_last_one(reg):
    await turn_on(reg, accounts="2")
    reg.app.state.register_throttle = None
    await sign_up(reg, "one")
    await portal_login(reg, "boss", GOOD)
    assert (await reg.get("/register")).status_code == 200
    await sign_up(reg, "two")
    assert (await reg.get("/register")).status_code == 404
    await sign_up(reg, "three")
    assert user_row(reg, "one") and user_row(reg, "two") and user_row(reg, "three") is None
    assert "registration.close" in audit_actions(reg)


async def test_a_failed_attempt_does_not_use_a_place(reg):
    await turn_on(reg, accounts="1")
    await sign_up(reg, "x y")
    with reg.sm() as s:
        assert registration._get(s, registration.LEFT) == "1"


async def test_the_time_limit_is_checked_when_somebody_registers(reg):
    await turn_on(reg, hours="1")
    with reg.sm() as s:
        assert registration.state(s, datetime.now(UTC) + timedelta(minutes=59)).is_open
        assert registration.state(s, datetime.now(UTC) + timedelta(minutes=61)).closed == "expired"


async def test_the_address_is_limited_even_for_failed_attempts(reg, monkeypatch):
    monkeypatch.setattr(settings, "register_per_ip_hour", 3)
    await turn_on(reg)
    for _ in range(3):
        await sign_up(reg, "bad name")
    r = await sign_up(reg, "fine")
    assert r.headers["location"] == "/register" and user_row(reg, "fine") is None


async def test_nothing_to_offer_without_a_requestable_group(admin):
    r = await admin.post("/admin/registration", data={"csrf_token": await csrf_of_page(admin, "/admin/users"), "mode": "open"})
    assert r.status_code == 303
    assert "No group can be requested" in (await admin.get("/admin/users")).text
    assert (await admin.get("/register")).status_code == 404


async def test_losing_the_last_requestable_group_closes_registration(reg):
    await turn_on(reg)
    with reg.sm() as s:
        s.scalars(select(Group).where(Group.name == "guests")).one().requestable = False
        s.commit()
    assert (await reg.get("/register")).status_code == 404
    assert "/register" not in (await reg.get("/login")).text


async def test_the_switch_is_one_for_all_administrators(reg):
    await turn_on(reg, "approval", hours="24", accounts="5")
    make_user(reg.sm, "boss2", password=GOOD, admin=True)
    reg.cookies.clear()
    await portal_login(reg, "boss2", GOOD)
    page = (await reg.get("/admin/users")).text
    assert "open, with approval" in page and "5 accounts still allowed" in page
    await reg.post("/admin/registration", data={"csrf_token": await csrf_of_page(reg, "/admin/users"), "mode": "off"})
    assert (await reg.get("/register")).status_code == 404


async def test_invalid_switch_values_change_nothing(reg):
    for kw in ({"hours": "abc"}, {"accounts": "0"}, {"accounts": "99999"}, {"hours": "-3"}, {"mode": "bogus"}):
        await turn_on(reg, **{"mode": "open", **kw})
    assert (await reg.get("/register")).status_code == 404


async def test_deleting_a_waiting_account_removes_its_mark(reg):
    await turn_on(reg, "approval")
    await sign_up(reg, "maria")
    from spoolsteward.auth.users import delete_user
    with reg.sm() as s:
        delete_user(s, user_row(reg, "maria"))
        s.commit()
        assert s.scalar(select(func.count(Registration.id))) == 0


async def test_plain_http_is_refused(reg, monkeypatch):
    await turn_on(reg)
    monkeypatch.setattr(settings, "allow_insecure_auth", False)
    r = await reg.post("http://gw.test/register", data={"username": "x", "password": GOOD, "confirm": GOOD, "group_id": str(reg.gid)})
    assert r.status_code == 403


@pytest.mark.parametrize("code", ["it", "es", "ru", "zh"])
async def test_the_new_pages_render_in_every_language(reg, monkeypatch, code):
    monkeypatch.setattr(settings, "language", code)
    await turn_on(reg, "approval", hours="24", accounts="5")
    await sign_up(reg, "maria")
    await portal_login(reg, "boss", GOOD)
    for path in ("/admin/users", "/admin/requests", "/register", "/login"):
        r = await reg.get(path)
        assert r.status_code == 200 and "%(" not in r.text, path
