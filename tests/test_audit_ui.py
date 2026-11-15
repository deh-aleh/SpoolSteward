"""Audit page (/admin/jobs) and the administrator switches: paging, shortened texts with popups, device/action
columns, auto-refresh, sticky menu, printer block, maintenance mode, mDNS policy, grant tooltips."""

import base64
import re
import time
from datetime import UTC, datetime, timedelta
from spoolsteward.timeutil import local_tz

import httpx
import pytest
from sqlalchemy import select

from spoolsteward.admin.accounts import ACTIONS_PAGE
from spoolsteward.admin.audit_view import COMMENT_MAX, FILE_MAX, NOTE_MAX
from spoolsteward.config import settings
from spoolsteward.db.models import (
    AdminAudit, JobKind, JobLog, JobState, Metric, Period, PrinterControl, QuotaGrant, RequestScope, SubjectType, User,
)
from spoolsteward.ipp import codec as c
from spoolsteward.mdns import apply_policy
from spoolsteward.policy import control
from spoolsteward.policy.rules import set_limit
from tests.conftest import CUPS_TEST_URL, csrf_from, csrf_of_page, make_user, portal_login, requires_cups

GOOD = "correct horse battery"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
       b"trailer<</Root 1 0 R/Size 4>>\n%%EOF\n")
LONG_NAME = "quarterly-report-of-the-accounting-department-with-attachments-and-closing-notes-final-v7.pdf"
LONG_COMMENT = "please print double-sided for the Thursday meeting in the main hall, thank you very much"


def add_jobs(cl, n=1, **kw):
    with cl.sm() as s:
        for i in range(n):
            s.add(JobLog(**{"user_name": "zed", "printer": "virtual", "title": f"f{i}.pdf", "state": JobState.completed, **kw}))
        s.commit()


def row_count(html: str) -> int:
    return html.count('<li class="jr">')


def rows_of(html: str) -> list[str]:
    """The rows of the log, each as its summary + detail text."""
    return re.findall(r'<li class="jr">(.*?)</li>', html, re.S)


# ---------------------------------------------------------------- paging

async def test_every_audit_page_holds_at_most_30_actions(admin):
    add_jobs(admin, 65)
    p1 = (await admin.get("/admin/jobs")).text
    p3 = (await admin.get("/admin/jobs?page=3")).text
    assert row_count(p1) == 30 and "Page 1 of 3" in p1
    assert row_count((await admin.get("/admin/jobs?page=2")).text) == 30 and row_count(p3) == 5


# ---------------------------------------------------------------- shortened texts

async def test_the_whole_text_of_a_row_is_in_its_detail_and_nothing_is_a_tiny_button(admin):
    add_jobs(admin, title=LONG_NAME, options_json={"document_name": LONG_NAME + ".bak", "comment": LONG_COMMENT, "via": "web",
                                                 "document_format": "application/pdf", "copies": 3})
    add_jobs(admin, title="short.pdf", options_json={"comment": "ok"})
    page = (await admin.get("/admin/jobs")).text
    long_row = next(x for x in rows_of(page) if "quarterly-report" in x)
    summary, detail = long_row.split('<div class="detail">')
    assert LONG_NAME in summary                                          # the whole name is in the row: the stylesheet shortens it on screen
    assert LONG_COMMENT in detail and LONG_NAME + ".bak" in detail and "application/pdf" in detail and "web portal" in detail
    assert 'class="dots"' not in page and "ⓘ" not in page and "data-open-next" not in page and "data-open-td" not in page


async def test_a_refusal_shows_its_reason_in_the_row_and_the_detail_copies_it(admin):
    reason = "weekly page limit would be exceeded (used 48, this document 20, limit 50) and some more text"
    add_jobs(admin, state=JobState.denied, denied_reason=reason)
    add_jobs(admin, state=JobState.completed, denied_reason=None, title="fine.pdf")
    page = (await admin.get("/admin/jobs")).text
    refused = next(x for x in rows_of(page) if reason in x)
    summary, detail = refused.split('<div class="detail">')
    assert f'<span class="jl2 s-denied">{reason}</span>' in summary      # in red, where the printer and the pages would be
    assert f'data-copy class="copytext">{reason}</div>' in detail and 'class="copy"' in detail   # the whole note, with a copy button
    fine = next(x for x in rows_of(page) if "fine.pdf" in x)
    assert "s-denied" not in fine.split('<div class="detail">')[0] and "<dt>Note</dt>" not in fine


# ---------------------------------------------------------------- device / action

async def test_device_kind_and_pages_are_on_the_second_line_of_a_row(admin):
    admin.app.state.scanner_device_cache = (time.monotonic(), "virtual")   # the print queue that shares the scanner's device
    add_jobs(admin, kind=JobKind.scan, printer="scanner", title="scan", options_json={"via": "web", "source": "adf"})
    add_jobs(admin, kind=JobKind.scan, printer="scanner", title="scan", options_json={"via": "web", "source": "platen"})
    add_jobs(admin, printer="hp", title="a.pdf", pages=3, options_json={"color": "monochrome", "sides": "two-sided-long-edge"})
    add_jobs(admin, printer="hp", title="b.pdf")
    page = (await admin.get("/admin/jobs")).text
    rows = rows_of(page)
    scans = [x for x in rows if "· scan" in x]
    prints = [x for x in rows if "· print" in x]
    assert len(scans) == 2 and len(prints) == 2
    assert all("virtual · scan" in x for x in scans) and "scanner ·" not in page      # never the literal "scanner"
    assert sum("<abbr" in x.split('<div class="detail">')[0] for x in scans) == 1     # ADF badge only when the feeder was used
    assert all("<dt>Colour</dt>" not in x for x in scans)                               # no print specs on a scan row
    a = next(x for x in prints if "a.pdf" in x)
    assert "hp · print · 3 pages" in a and "<dd>black and white</dd>" in a and "<dd>double-sided (long edge)</dd>" in a
    b_ = next(x for x in prints if "b.pdf" in x)
    assert "<dd>printer default</dd>" in b_ and "<dd>normal</dd>" in b_


async def test_rows_are_grouped_by_day_with_the_day_written_once(admin):
    add_jobs(admin, 2)
    add_jobs(admin, 1, ts=datetime.now(UTC) - timedelta(days=1))
    page = (await admin.get("/admin/jobs")).text
    assert page.count('class="dayhead">Today<') == 1 and page.count('class="dayhead">Yesterday<') == 1


async def test_csv_uses_the_device_name_and_carries_the_print_specs(admin):
    admin.app.state.scanner_device_cache = (time.monotonic(), "virtual")
    add_jobs(admin, kind=JobKind.scan, printer="scanner", title="scan", options_json={"source": "adf"})
    add_jobs(admin, printer="hp", title="a.pdf", options_json={"color": "color", "sides": "one-sided"})
    lines = (await admin.get("/admin/jobs.csv")).text.splitlines()
    assert lines[0].startswith("n,time,user,kind") and lines[0].endswith("adf,color,sides")
    assert ",virtual," in lines[2] and ",adf," in lines[2] + "," and lines[1].endswith(",,colour,normal")


# ---------------------------------------------------------------- auto refresh

async def test_auto_refresh_defaults_to_30_seconds_and_is_set_in_the_settings(admin):
    page = (await admin.get("/admin/jobs")).text
    assert 'data-ar-secs="30"' in page and 'data-ar-on="1"' in page and "Refresh every 30 s" in page
    assert 'name="seconds" value="15"' in page and 'name="seconds" value="60"' in page      # the interval is chosen next to the switch
    assert 'name="seconds"' not in (await admin.get("/me/settings")).text
    tok = await csrf_of_page(admin, "/me/settings")
    r = await admin.post("/me/settings/refresh", data={"csrf_token": tok, "seconds": "90", "next": "/admin/jobs"})
    assert r.headers["location"] == "/admin/jobs"                                       # back to the page it was chosen on
    assert 'data-ar-secs="90"' in (await admin.get("/admin/jobs")).text
    r = await admin.post("/me/settings/refresh", data={"csrf_token": tok, "seconds": "2"})            # below the minimum
    assert "between 5 and 3600" in (await admin.get("/me/settings")).text and r.status_code == 303
    assert 'data-ar-secs="90"' in (await admin.get("/admin/jobs")).text
    await admin.post("/me/settings/refresh", data={"csrf_token": tok, "seconds": "0"})
    page = (await admin.get("/admin/jobs")).text
    assert 'data-ar-on="0"' in page and 'data-ar-secs="30"' in page                      # off at first; the page's switch can still turn it on


async def test_only_administrators_see_the_refresh_setting(portal):
    make_user(portal.sm, "pia", password=GOOD)
    await portal_login(portal, "pia", GOOD)
    assert 'name="seconds"' not in (await portal.get("/me/settings")).text


# ---------------------------------------------------------------- layout

async def test_the_sidebar_stays_in_place_and_maintenance_lives_in_the_system_page(admin):
    page = (await admin.get("/admin/jobs")).text
    css = (await admin.get("/admin/static/css/app.css")).text
    assert "#sidebar { position:sticky; top:0" in css and 'id="sidebar"' in page
    assert 'class="maint' not in page and "Start maintenance" not in page            # no longer a button on every page
    system = (await admin.get("/admin/system")).text
    assert "Start maintenance" in system and 'action="/admin/maintenance"' in system


# ---------------------------------------------------------------- users: grant tooltips

async def test_user_tooltip_shows_when_a_temporary_grant_expires(admin):
    uid = make_user(admin.sm, "gina", password=GOOD, group="staff")
    until = datetime.now(UTC) + timedelta(days=2)
    with admin.sm() as s:
        set_limit(s, SubjectType.user, uid, Metric.jobs, 5, Period.weekly)
        set_limit(s, SubjectType.user, uid, Metric.pages, 50, Period.weekly)
        now = datetime.now(UTC)
        s.add_all([QuotaGrant(user_id=uid, metric=Metric.jobs, amount=3, scope=RequestScope.temporary, valid_from=now - timedelta(hours=1), valid_until=until),
                   QuotaGrant(user_id=uid, metric=Metric.jobs, amount=2, scope=RequestScope.permanent, valid_from=now - timedelta(hours=1)),
                   QuotaGrant(user_id=uid, metric=Metric.pages, amount=10, scope=RequestScope.temporary, valid_from=now - timedelta(hours=1), valid_until=until)])
        s.commit()
    page = (await admin.get("/admin/users")).text
    row = next(r for r in page.split("<tr>") if "gina" in r)
    tips = re.findall(r'title="([^"]+)"', row)
    assert any("+3 · temporary, expires on" in t and "+2 · permanent" in t for t in tips)       # jobs
    assert any("+10 · temporary, expires on" in t for t in tips)                                 # pages
    assert until.astimezone(local_tz()).strftime("%Y-%m-%d")[:7] in " ".join(tips)


# ---------------------------------------------------------------- printer block / maintenance (web path, real CUPS)

async def web_print(cl, name="x.pdf", token=None):
    return await cl.post("/me/print", data={"queue": "virtual", "copies": "1", "csrf_token": token or await csrf_of_page(cl, "/me")},
                         files={"file": (name, PDF, "application/pdf")})


def last_job(cl):
    with cl.sm() as s:
        return s.scalars(select(JobLog).order_by(JobLog.id.desc())).first()


@pytest.fixture
async def two(portal):
    portal.app.state.upstream = httpx.AsyncClient(base_url=CUPS_TEST_URL, timeout=10)
    portal.app.state.queues_cache = None
    make_user(portal.sm, "boss", password=GOOD, admin=True)
    make_user(portal.sm, "ann", password=GOOD, group="staff")
    yield portal
    await portal.app.state.upstream.aclose()


async def as_user(cl, name):
    await cl.post("/logout", data={"csrf_token": await csrf_of_page(cl, "/me")}) if cl.cookies else None
    cl.cookies.clear()
    await portal_login(cl, name, GOOD)
    return await csrf_of_page(cl, "/me")


@requires_cups
async def test_blocked_printer_stops_everybody_administrators_included(two):
    tok = await as_user(two, "boss")
    r = await two.post("/admin/printers/virtual/block", data={"csrf_token": tok, "on": "1"})
    assert r.status_code == 303
    with two.sm() as s:
        assert s.get(PrinterControl, "virtual").blocked
        assert s.scalars(select(AdminAudit).where(AdminAudit.action == "printer.block")).one().detail_json == {"printer": "virtual"}
    await web_print(two, "admin.pdf", tok)                                      # an administrator, still refused
    j = last_job(two)
    assert j.state is JobState.denied and j.denied_reason == control.BLOCKED_REASON and "administrators included" in j.denied_reason
    assert 'value="virtual"' not in (await two.get("/me/print")).text                  # a blocked printer is not even offered
    tok = await as_user(two, "ann")
    await web_print(two, "ann.pdf", tok)
    assert last_job(two).denied_reason == control.BLOCKED_REASON
    tok = await as_user(two, "boss")
    page = (await two.get("/admin/printers")).text
    assert "Blocked for everyone, admins included" in page and ">Unblock<" in page and "Hide from the network" in page
    await two.post("/admin/printers/virtual/block", data={"csrf_token": tok, "on": "0"})
    await web_print(two, "again.pdf", tok)
    assert last_job(two).state is JobState.accepted


@requires_cups
async def test_maintenance_stops_users_but_not_administrators(two):
    tok = await as_user(two, "boss")
    assert "Start maintenance" in (await two.get("/admin/system")).text
    r = await two.post("/admin/maintenance", data={"csrf_token": tok, "on": "1", "next": "/admin/jobs"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/jobs"
    with two.sm() as s:
        assert control.is_maintenance(s)
    page = (await two.get("/admin/jobs")).text
    assert "End maintenance" in (await two.get("/admin/system")).text and "Maintenance in progress" in page
    await web_print(two, "boss.pdf", tok)                                        # administrators keep working
    assert last_job(two).state is JobState.accepted
    tok = await as_user(two, "ann")
    assert "Maintenance in progress: printing and scanning are stopped." in (await two.get("/me")).text
    await web_print(two, "ann.pdf", tok)
    j = last_job(two)
    assert j.state is JobState.denied and j.denied_reason == control.MAINTENANCE_REASON
    tok = await as_user(two, "boss")
    await two.post("/admin/maintenance", data={"csrf_token": tok, "on": "0", "next": "https://evil.example/"})   # no open redirect
    with two.sm() as s:
        assert not control.is_maintenance(s)
        assert {a.action for a in s.scalars(select(AdminAudit))} >= {"maintenance.on", "maintenance.off"}
    tok = await as_user(two, "ann")
    await web_print(two, "ann2.pdf", tok)
    assert last_job(two).state is JobState.accepted


async def test_switches_are_admin_only_and_need_csrf(portal):
    make_user(portal.sm, "pia", password=GOOD)
    await portal_login(portal, "pia", GOOD)
    tok = await csrf_of_page(portal, "/me")
    for path in ("/admin/maintenance", "/admin/printers/virtual/block", "/admin/printers/virtual/mdns"):
        assert (await portal.post(path, data={"csrf_token": tok, "on": "1"})).status_code == 403
    with portal.sm() as s:
        assert not control.is_maintenance(s) and s.scalars(select(PrinterControl)).first() is None
    await portal.post("/logout", data={"csrf_token": tok})
    make_user(portal.sm, "boss", password=GOOD, admin=True)
    await portal_login(portal, "boss", GOOD)
    assert (await portal.post("/admin/maintenance", data={"on": "1", "csrf_token": "wrong"})).status_code == 403
    assert (await portal.post("/admin/printers/bad%20name!/block", data={"csrf_token": await csrf_of_page(portal, "/me"), "on": "1"})).status_code == 404


# ---------------------------------------------------------------- mDNS

async def test_mdns_policy_feed_and_filter(admin, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "s3cret")
    tok = await csrf_of_page(admin, "/me")
    await admin.post("/admin/printers/Virtual/mdns", data={"csrf_token": tok, "on": "1"})
    assert (await admin.get("/mdns/policy")).status_code == 404                                  # no token, no answer
    r = await admin.get("/mdns/policy", headers={"X-Mdns-Token": control.mdns_token()})
    assert r.json() == {"maintenance": False, "hidden": ["virtual"], "offline": [], "scanners": []}
    queues = [{"name": "virtual"}, {"name": "HP"}]
    policy = {"maintenance": False, "hidden": {"virtual"}}
    assert apply_policy(queues, policy) == [{"name": "HP"}]
    assert apply_policy(queues, {"maintenance": True, "hidden": set()}) == []                    # maintenance withdraws everything
    assert apply_policy(queues, None) == queues                                                  # policy unknown: announce as before
    await admin.post("/admin/maintenance", data={"csrf_token": tok, "on": "1"})
    assert (await admin.get("/mdns/policy", headers={"X-Mdns-Token": control.mdns_token()})).json()["maintenance"] is True


async def test_mdns_policy_refuses_everybody_without_a_secret_key(admin, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "")
    assert (await admin.get("/mdns/policy")).status_code == 404
    assert (await admin.get("/mdns/policy", headers={"X-Mdns-Token": ""})).status_code == 404
    assert (await admin.get("/mdns/policy", headers={"X-Mdns-Token": control.mdns_token()})).status_code == 404   # the token of the empty key


async def test_mdns_policy_answers_404_and_not_500_to_a_header_with_odd_characters(admin, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "s3cret")
    r = await admin.get("/mdns/policy", headers={"X-Mdns-Token": "caf\xe9".encode("latin-1")})
    assert r.status_code == 404


# ---------------------------------------------------------------- IPP clients: colour / sides are audited

@pytest.fixture
async def ipp(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from spoolsteward.auth.throttle import Throttle
    from spoolsteward.db.models import Base
    from spoolsteward.main import app
    from tests.conftest import StubRadius

    monkeypatch.setattr(settings, "allow_insecure_auth", True)
    monkeypatch.setattr(settings, "ipp_auth", "keys+radius")
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False)
    app.state.auth = StubRadius({"mario": "pw1", "boss": "pw2"})
    app.state.throttle = Throttle(5, 300)
    app.state.upstream = httpx.AsyncClient(base_url=CUPS_TEST_URL, timeout=10)
    with app.state.sessionmaker() as s:
        s.add(User(username="boss", is_admin=True, provider="radius"))
        s.commit()
    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://gw.test:8631") as cl:
        cl.sm = app.state.sessionmaker
        yield cl
    await app.state.upstream.aclose()


def ipp_print(user="mario", pw="pw1", **job_attrs):
    req = c.make_request(c.PRINT_JOB, 1, printer_uri="ipp://gw.test:8631/printers/virtual", document_format="text/plain",
                         job_name="from-ipp.txt")
    if job_attrs:
        req.groups.append(c.Group(c.TAG_JOB, [c.Attr(k, [c.Val(c.TAG_KEYWORD, v)]) for k, v in job_attrs.items()]))
    req.data = b"hello\n"
    auth = {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}
    return dict(content=c.encode(req), headers={"Content-Type": "application/ipp", **auth})


@requires_cups
async def test_ipp_print_records_colour_and_sides_and_respects_the_switches(ipp):
    r = await ipp.post("/printers/virtual", **ipp_print(**{"print-color-mode": "monochrome", "sides": "two-sided-long-edge"}))
    assert c.decode(r.content).code < 0x100
    with ipp.sm() as s:
        j = s.scalars(select(JobLog)).one()
        assert j.options_json["color"] == "monochrome" and j.options_json["sides"] == "two-sided-long-edge"
        control.set_printer_flag(s, "virtual", "blocked", True)
        s.commit()
    r = await ipp.post("/printers/virtual", **ipp_print())                       # blocked: the client is told why
    out = c.decode(r.content)
    assert out.code == c.STATUS_NOT_POSSIBLE and "administrators included" in out.get(c.TAG_OPERATION, "status-message")
    assert "more quota" not in out.get(c.TAG_OPERATION, "status-message")        # not a quota matter
    r = await ipp.post("/printers/virtual", **ipp_print("boss", "pw2"))           # administrators are refused too
    assert c.decode(r.content).code == c.STATUS_NOT_POSSIBLE
    with ipp.sm() as s:
        control.set_printer_flag(s, "virtual", "blocked", False)
        control.set_maintenance(s, True)
        s.commit()
    assert c.decode((await ipp.post("/printers/virtual", **ipp_print())).content).code == c.STATUS_NOT_POSSIBLE
    assert c.decode((await ipp.post("/printers/virtual", **ipp_print("boss", "pw2"))).content).code < 0x100
    states = [(j.user_name, j.state.value) for j in ipp.sm().scalars(select(JobLog).order_by(JobLog.id))]
    assert states == [("mario", "accepted"), ("mario", "denied"), ("boss", "denied"), ("mario", "denied"), ("boss", "accepted")]


async def test_sidebar_has_the_brand_the_menu_and_log_out(portal):
    make_user(portal.sm, "ada", password="correct horse battery", admin=True)
    make_user(portal.sm, "pia", password="correct horse battery")
    await portal_login(portal, "ada", "correct horse battery")
    page = (await portal.get("/me")).text
    assert 'class="brand"' in page and '<span class="bname">SpoolSteward</span>' in page and 'class="who" title="ada">ada<' in page
    assert 'aria-label="Log out"' in page and "Management" in page
    for label in ("Print", "Scan", "Account", "Devices", "Log", "People", "Requests", "Printers", "System", "Notices", "Guide", "Settings"):
        assert f'<span class="lbl">{label}</span>' in page, label
    assert 'href="/me"' in page and 'aria-current="page"' in page                       # the page you are on is marked
    await portal.post("/logout", data={"csrf_token": csrf_from(page)})
    await portal_login(portal, "pia", "correct horse battery")
    user_page = (await portal.get("/me")).text
    assert "Management" not in user_page and '<span class="lbl">People</span>' not in user_page and '<span class="lbl">Devices</span>' in user_page


def test_notice_rate_limit_follows_the_log_level(monkeypatch):
    from spoolsteward import notices
    from spoolsteward.config import settings

    for level, seconds in (("DEBUG", 60), ("INFO", 86400), ("WARNING", 3 * 86400), ("ERROR", 7 * 86400), ("nonsense", 86400)):
        monkeypatch.setattr(settings, "log_level", level)
        assert notices.interval() == seconds
    monkeypatch.setattr(settings, "notice_interval", 5)
    assert notices.interval() == 5


async def test_refused_anonymous_scans_make_one_notice_a_day_not_one_per_try(portal, monkeypatch):
    from sqlalchemy import select

    from spoolsteward import notices
    from spoolsteward.db.models import AdminAudit, Notice

    monkeypatch.setattr(settings, "log_level", "INFO")
    notices._state.clear()
    sm = portal.sm
    t0 = 1_000_000.0
    first = [notices.report(sm, "escl_anonymous_refused", "10.0.0.7", {"path": "ScanJobs"}, now=t0 + i) for i in range(100)]
    assert first[0] is True and not any(first[1:])                       # 100 tries, one report
    assert notices.pending("escl_anonymous_refused", "10.0.0.7") == 99
    assert notices.report(sm, "escl_anonymous_refused", "10.0.0.8", now=t0 + 5)   # another source is reported on its own
    assert notices.report(sm, "escl_anonymous_refused", "10.0.0.7", now=t0 + 86400 + 1)   # a day later: reported again
    with sm() as s:
        row = s.scalars(select(Notice).where(Notice.key == "10.0.0.7")).one()
        assert row.count == 101                                          # the 99 repeats are added to the count
    # an administrator sees them and can dismiss them; the bell is for administrators only
    make_user(sm, "ada", password="correct horse battery", admin=True)
    make_user(sm, "pia", password="correct horse battery")
    await portal_login(portal, "ada", "correct horse battery")
    page = (await portal.get("/admin/notices")).text
    assert "10.0.0.7" in page and "SPOOLSTEWARD_ESCL_ANONYMOUS" in page
    def bell(html):    # the counter on the Notices entry of the menu
        entry = re.search(r'<a class="navitem[^"]*" href="/admin/notices".*?</a>', html, re.S).group(0)
        return re.search(r'class="count"[^>]*>(\d+)<', entry)

    assert bell(page) is None and bell((await portal.get("/me")).text) is None                    # opening the list is "seeing" it
    assert notices.report(sm, "escl_anonymous_refused", "10.0.0.9", now=time.time())                # something new happens
    assert bell((await portal.get("/me")).text).group(1) == "1"                                    # a counter again
    await portal.get("/admin/notices")
    assert bell((await portal.get("/me")).text) is None
    csrf = csrf_from(page)
    with sm() as s:
        nid = s.scalars(select(Notice).where(Notice.key == "10.0.0.7")).one().id
    assert (await portal.post(f"/admin/notices/{nid}/dismiss", data=dict(csrf_token=csrf))).status_code == 303
    with sm() as s:
        assert s.get(Notice, nid).dismissed_by == "ada"
        assert "notice.dismiss" in [a.action for a in s.scalars(select(AdminAudit))]
    await portal.post("/logout", data=dict(csrf_token=csrf))
    await portal_login(portal, "pia", "correct horse battery")
    assert (await portal.get("/admin/notices")).status_code == 403
    assert 'href="/admin/notices"' not in (await portal.get("/me")).text


async def test_healthz_shows_only_what_the_administrator_chose(portal, monkeypatch):
    from spoolsteward import cups_client

    portal.app.state.upstream = httpx.AsyncClient(base_url="http://cups", transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    async def fake_queues(app, probe=True):
        return [{"name": "usb1", "device_uri": "ipp://ipp-usb:60000/ipp/print", "virtual": False},
                {"name": "old", "device_uri": "usb://HP/Laser?serial=1", "virtual": False},
                {"name": "office", "device_uri": "ipp://192.168.1.60/ipp/print", "virtual": False},
                {"name": "pdf", "device_uri": "cups-pdf:/", "virtual": True}]

    monkeypatch.setattr(cups_client, "list_queues", fake_queues)
    monkeypatch.setattr(settings, "usb_bridge_host", "ipp-usb")
    monkeypatch.setattr(settings, "healthz_info", "")
    assert (await portal.get("/healthz")).json() == {"status": "ok"}                         # the default: nothing else
    monkeypatch.setattr(settings, "healthz_info", "version")
    body = (await portal.get("/healthz")).json()
    assert set(body) == {"status", "version"} and body["version"]
    monkeypatch.setattr(settings, "healthz_info", " Version , printers ,nonsense")
    body = (await portal.get("/healthz")).json()
    assert body["printers"] == {"usb": 2, "network": 1, "virtual": 1, "total": 4}
    portal.app.state.upstream = httpx.AsyncClient(base_url="http://cups", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    r = await portal.get("/healthz")                                                           # degraded: no counts, still the version
    assert r.status_code == 503 and "printers" not in r.json()
    del portal.app.state.upstream


# ---------------------------------------------------------------- audit numbering

async def test_audit_detail_has_the_number_and_the_csv_too(admin):
    with admin.sm() as s:
        s.add(JobLog(user_name="zed", printer="p", title="t.pdf", state=JobState.completed))
        s.commit()
        n = s.scalars(select(JobLog)).first().id
    page = (await admin.get("/admin/jobs")).text
    assert f"<dt>No.</dt><dd>{n}</dd>" in page
    assert (await admin.get("/admin/jobs.csv")).text.splitlines()[0].startswith("n,time,user,kind")


def _job(sm, user_id, **kw):
    with sm() as s:
        j = JobLog(user_id=user_id, kind=kw.pop("kind", JobKind.print), printer=kw.pop("printer", "p1"), title="a.pdf",
                   state=kw.pop("state", JobState.completed), ts=datetime.now(UTC), **kw)
        s.add(j)
        s.commit()


async def test_audit_rows_have_no_stripes_the_states_are_in_the_guide_and_guests_show_where_they_came_from(portal, admin):
    with portal.sm() as s:
        boss = s.scalars(select(User).where(User.username == "boss")).one().id
        guest = User(username="unknown-guest", provider="local", enabled=False)
        s.add(guest)
        s.commit()
        gid = guest.id
    _job(portal.sm, gid, kind=JobKind.scan, printer="scanner",
         options_json={"via": "escl", "guest_ip": "10.1.2.3", "guest_host": "pc-room3.school.lan"})
    _job(portal.sm, boss)
    page = (await portal.get("/admin/jobs")).text
    assert "zebra" not in page and 'id="states-help"' not in page and "info-lg" not in page
    assert "What “Completed” means" in page and "/docs/en/audit#1-print-and-scan-audit" in page    # the explanation is in the guide
    assert "10.1.2.3" in page and "pc-room3.school.lan" in page and "Scan without sign-in" in page
    assert page.count("Scan without sign-in") == 1                   # only the guest row has the information
    # no hostname known: say so instead of leaving a hole
    _job(portal.sm, gid, kind=JobKind.scan, printer="scanner", options_json={"via": "escl", "guest_ip": "10.9.9.9"})
    assert "not available" in (await portal.get("/admin/jobs")).text


async def test_actions_page_is_30_rows_that_open(portal, admin):
    with portal.sm() as s:
        for i in range(ACTIONS_PAGE + 5):
            s.add(AdminAudit(actor_name="boss", action=f"test.{i}"))
        s.commit()
    page = (await portal.get("/admin/actions")).text
    assert ACTIONS_PAGE == 30
    assert page.count('class="jn mono">test.') == 30 and "Page 1 of 2" in page
    assert page.count("<details>") == 30                              # every action opens to show its details
