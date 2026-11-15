"""The pages of the redesigned portal: what is new in them (the account lists the latest prints, a quota is a line of ticks,
the System page holds maintenance / update / backups, the Log groups rows by day...)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from spoolsteward.admin.common import day_label, near_time, next_day
from spoolsteward.db.models import JobKind, JobLog, JobState, Metric, Period, SubjectType, User
from spoolsteward.policy.rules import set_limit
from tests.conftest import csrf_from, make_user, portal_login

GOOD = "correct horse battery"


def _job(sm, user_id, name, title, state=JobState.completed, **kw):
    with sm() as s:
        s.add(JobLog(user_id=user_id, user_name=name, kind=kw.pop("kind", JobKind.print), printer="p1", title=title, state=state,
                     ts=kw.pop("ts", datetime.now(UTC)), **kw))
        s.commit()


async def test_the_account_lists_the_latest_ten_prints_with_the_reason_of_a_refusal(portal):
    ann = make_user(portal.sm, "ann", password=GOOD)
    bob = make_user(portal.sm, "bob", password=GOOD)
    for i in range(12):
        _job(portal.sm, ann, "ann", f"file{i}.pdf", pages=2, ts=datetime.now(UTC) - timedelta(minutes=12 - i))
    _job(portal.sm, ann, "ann", "refused.pdf", JobState.denied, denied_reason="weekly page limit would be exceeded")
    _job(portal.sm, bob, "bob", "not-yours.pdf")
    await portal_login(portal, "ann", GOOD)
    page = (await portal.get("/me")).text
    assert page.count('<li class="jr">') == 10 and "file0.pdf" not in page and "file3.pdf" in page    # the latest ten, not the oldest
    assert "not-yours.pdf" not in page                                                                # nobody else's
    assert '<span class="jl2 s-denied">weekly page limit would be exceeded</span>' in page            # the reason, in the row
    assert "<details>" not in page.split('id="recent"')[1].split("</section>")[0]                      # the rows of the account do not open


async def test_quota_is_a_line_of_ticks_with_what_is_left(portal):
    ann = make_user(portal.sm, "ann", password=GOOD)
    with portal.sm() as s:
        set_limit(s, SubjectType.user, ann, Metric.pages, 20, Period.weekly)
        s.commit()
    for _ in range(3):
        _job(portal.sm, ann, "ann", "a.pdf", pages=2, state=JobState.completed)
    await portal_login(portal, "ann", GOOD)
    page = (await portal.get("/me")).text
    assert "14 left of 20" in page and page.count("<i></i>") + page.count('<i class="used"></i>') == 20
    assert page.count('<i class="used"></i>') == 6                                                     # one tick for every page used
    assert "Resets on " in page
    portal.app.state.queues_cache = (__import__("time").monotonic(), [{"name": "p1", "info": "", "model": "", "online": True}])
    printed = (await portal.get("/me/print")).text
    assert "14 pages left until" in printed                                                          # also next to the Print button


async def test_the_phone_menu_page_and_the_old_backup_address(portal):
    make_user(portal.sm, "ann", password=GOOD)
    make_user(portal.sm, "boss", password=GOOD, admin=True)
    await portal_login(portal, "ann", GOOD)
    menu = (await portal.get("/menu")).text
    assert 'href="/me/keys"' in menu and 'href="/me/settings"' in menu and 'href="/admin/system"' not in menu
    await portal.post("/logout", data={"csrf_token": csrf_from(menu)})
    await portal_login(portal, "boss", GOOD)
    menu = (await portal.get("/menu")).text
    assert 'href="/admin/system"' in menu and 'href="/admin/printers"' in menu and 'href="/admin/users"' in menu
    r = await portal.get("/admin/backups", follow_redirects=False)                                    # the page moved into System
    assert r.status_code == 303 and r.headers["location"] == "/admin/system#backup"


async def test_the_system_page_has_maintenance_update_backup_and_the_log_switch(admin):
    page = (await admin.get("/admin/system")).text
    for anchor in ("maintenance", "update", "backup", "log"):
        assert f'<section class="blk" id="{anchor}">' in page
    assert "Start maintenance" in page and "Printing and scanning are on." in page
    tok = csrf_from(page)
    await admin.post("/admin/maintenance", data={"csrf_token": tok, "on": "1", "next": "/admin/system#maintenance"})
    page = (await admin.get("/admin/system")).text
    assert "End maintenance" in page and "Maintenance in progress since " in page
    assert "Maintenance in progress: printing and scanning are stopped for users." in page           # the band at the top


async def test_the_log_groups_its_rows_by_day_and_the_tabs_are_links(admin):
    with admin.sm() as s:
        s.add(JobLog(user_name="zed", printer="p", title="old.pdf", state=JobState.completed, ts=datetime.now(UTC) - timedelta(days=3)))
        s.commit()
    page = (await admin.get("/admin/jobs")).text
    assert '<h2 class="dayhead">' in page and "old.pdf" in page
    for href in ("/admin/actions", "/admin/report", "/admin/archive"):
        assert f'href="{href}"' in page                                                                # every tab has its own address
    assert (await admin.get("/admin/report")).status_code == 200 and (await admin.get("/admin/actions")).status_code == 200


async def test_new_user_is_one_form_for_a_local_or_a_radius_account(portal, admin, monkeypatch):
    from spoolsteward.config import settings

    monkeypatch.setattr(settings, "radius_host", "radius.test")
    monkeypatch.setattr(settings, "radius_secret", "x")
    page = (await portal.get("/admin/users/new")).text
    tok = csrf_from(page)
    r = await portal.post("/admin/users/new", data={"csrf_token": tok, "kind": "local", "username": "loc9", "group_id": "0"})
    assert r.status_code == 200 and "Temporary password" in r.text                                    # local: the password is shown once
    r = await portal.post("/admin/users/new", data={"csrf_token": tok, "kind": "radius", "username": "rad9", "group_id": "0"})
    assert r.status_code == 303
    with portal.sm() as s:
        assert s.scalars(select(User).where(User.username == "loc9")).one().provider == "local"
        assert s.scalars(select(User).where(User.username == "rad9")).one().provider != "local"


async def test_an_administrator_has_a_tab_for_their_own_notices_and_one_for_the_gateway(portal):
    from spoolsteward import notices

    boss = make_user(portal.sm, "boss", password=GOOD, admin=True)
    notices.notify_user(portal.sm, boss, "key_revoked", {"label": "old laptop", "prefix": "abc"})
    await portal_login(portal, "boss", GOOD)
    own = (await portal.get("/admin/notices")).text                                                    # only their own are new: that tab opens
    assert "old laptop" in own and 'href="/admin/notices?tab=own"' in own and 'href="/admin/notices"' in own
    assert "No notices." in (await portal.get("/admin/notices?tab=gateway")).text


def test_dates_in_words_follow_the_language_of_the_page():
    from spoolsteward import i18n

    now = datetime.now(UTC)
    with i18n.using("it"):
        assert day_label(now) == "Oggi" and day_label(now - timedelta(days=1)) == "Ieri"
        assert near_time(now).startswith("oggi alle ") and next_day(now + timedelta(days=1)).startswith("domani alle ")
        assert " " in day_label(now - timedelta(days=4))                                              # "giovedì 12 novembre"
    with i18n.using("en"):
        assert day_label(now) == "Today" and near_time(now - timedelta(days=1)).startswith("yesterday at ")
