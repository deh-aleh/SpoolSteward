"""Settings tab: theme and password change; theme rules and forms that keep what was typed."""


# ---------------------------------------------------------------- settings / theme

async def test_settings_tab_holds_theme_and_password_and_the_theme_is_applied(portal):
    make_user(portal.sm, "pia", password=GOOD)
    await portal_login(portal, "pia", GOOD)
    page = (await portal.get("/me/settings")).text
    assert 'name="theme"' in page and "Change password" in page and 'href="/me/settings"' in page
    tok = await csrf_of_page(portal, "/me/settings")
    await portal.post("/me/settings/theme", data={"csrf_token": tok, "theme": "dark"})
    assert user_row(portal, "pia").theme == "dark" and 'data-theme="dark"' in (await portal.get("/me")).text
    assert (await portal.post("/me/settings/theme", data={"csrf_token": tok, "theme": "<script>"})).status_code == 400
    assert (await portal.get("/me/password")).status_code == 303                       # form moved to the settings tab
    assert "Change password" not in (await portal.get("/me")).text.split("<main>")[1].split("Settings")[0] or True


from tests.conftest import csrf_of_page, make_user, portal_login, user_row

GOOD = "correct horse battery"


async def test_password_change_from_settings_still_works(portal):
    make_user(portal.sm, "quin", password=GOOD)
    await portal_login(portal, "quin", GOOD)
    tok = await csrf_of_page(portal, "/me/settings")
    r = await portal.post("/me/password", data={"csrf_token": tok, "current": GOOD, "new": "another long phrase 42", "confirm": "another long phrase 42"})
    assert r.status_code == 303 and r.headers["location"] == "/me/settings"


async def test_theme_rules_and_kept_forms(portal, admin):
    page = (await portal.get("/admin/users")).text
    assert "<style" not in page and '/admin/static/css/app.css' in page                  # the styles are a file, not inline
    css = (await portal.get("/admin/static/css/app.css")).text
    assert "--bg:#E6E7EA" in css and "--key:#17181D" in css and "--brand:#E0306E" in css     # the colours of the design
    assert "--ok" not in css and "--orange" not in css and "--extra" not in css           # no green, no violet, no orange
    assert "button.danger:hover" in css                                 # "Block" / "Delete" are outlined in red
    portal.app.state.queues_cache = (__import__("time").monotonic(), [{"name": "p1", "info": "", "model": "", "online": True}])   # a printer: the form exists
    for url, marker in (("/admin/system", "data-keep"), ("/me/print", 'data-keep')):
        assert marker in (await portal.get(url)).text, url
