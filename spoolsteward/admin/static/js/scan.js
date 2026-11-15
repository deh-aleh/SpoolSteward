// scan.html
(function () {
  var f = document.getElementById('sf');
  var D = JSON.parse(document.getElementById('sc-data').textContent);  // values from the server
  var L = D.L;  // texts for the script, in the language of the page
  function fmtL(s, v) { return s.replace(/%\((\w+)\)s/g, function (m, k) { return v[k]; }); }
  var where = f && document.getElementById('where');
  function say(text) { var e = document.getElementById('err'); if (e) { e.textContent = text; e.hidden = !text; } }
  var W = D.W;
  // scan window ("From a scan app"): the button tells the server "my scan app is about to scan"; the popup shows the address it saw
  var wb = document.getElementById('winbtn'), wd = document.getElementById('windlg'), wt = null, wend = 0;
  function wmark(on) { var n = document.getElementById('windot-note'); if (n) n.hidden = !on; }
  function wtick() {
    var left = Math.max(0, Math.round((wend - Date.now()) / 1000));
    document.getElementById('wincount').textContent = left > 0 ? fmtL(W.left, {m: Math.floor(left / 60), s: left % 60}) : W.over;
    if (left <= 0) { clearInterval(wt); wt = null; wmark(false); }
  }
  function wpost(url) {
    var tok = document.querySelector('[name=csrf_token]');
    return fetch(url, {method: 'POST', body: new URLSearchParams({csrf_token: tok ? tok.value : ''}), credentials: 'same-origin'})
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || L.error); return j; }); });
  }
  if (W && wb && wd) {
    wb.addEventListener('click', function () {
      wpost('/me/scan/window').then(function (j) {
        document.getElementById('winip').textContent = j.ip;
        var n = document.getElementById('winnote'), msg = j.proxy ? W.proxy : j.ipv6 ? W.v6 : '';
        n.textContent = msg; n.hidden = !msg;
        wend = Date.now() + j.seconds * 1000; wtick(); if (wt) clearInterval(wt); wt = setInterval(wtick, 1000);
        wmark(true);
        if (!wd.open) wd.showModal();
      }).catch(function (x) { say(x.message); });
    });
    document.getElementById('winok').addEventListener('click', function () { wd.close(); });
    document.getElementById('winstop').addEventListener('click', function () {
      wpost('/me/scan/window/close').then(function () { wend = 0; wtick(); wd.close(); }).catch(function () { wd.close(); });
    });
  }
  if (!f) return;
  var all = D.caps;  // scanner id -> what that device reported about itself
  var sc = document.getElementById('scanner');
  var src = document.getElementById('source'), dpi = document.getElementById('dpi'), note = document.getElementById('dpinote');
  var name = document.getElementById('filename'), fmtnote = document.getElementById('fmtnote');
  var go = document.getElementById('go'), wait = document.getElementById('wait');
  var canPick = !!window.showSaveFilePicker, handle = null;
  function cur() { return all[sc.value] || {}; }
  function val(n) { var c = f.querySelector('input[name=' + n + ']:checked'); return c ? c.value : ''; }
  function segFill(box, name, opts, keep) {  // the choice is a row of buttons, built from what this scanner offers
    box.innerHTML = '';
    opts.forEach(function (o) {
      var l = document.createElement('label'), i = document.createElement('input'), t = document.createElement('span');
      i.type = 'radio'; i.name = name; i.value = o[0]; i.checked = String(o[0]) === String(keep); t.textContent = o[1];
      if (o[2]) l.title = o[2];
      l.appendChild(i); l.appendChild(t); box.appendChild(l);
    });
    if (box.firstChild && !box.querySelector('input:checked')) box.querySelector('input').checked = true;
  }
  function dpis(which) {
    var c = cur();
    if (which === 'auto') { var a = (c.platen || {}).dpi || [], b = (c.adf || {}).dpi || []; var both = a.filter(function (x) { return b.indexOf(x) >= 0; }); return both.length ? both : a; }
    return (c[which] || {}).dpi || [];
  }
  function sources() {  // only what this scanner really has
    var c = cur(), keep = val('source');
    var opts = [];
    if (c.adf) opts.push(['auto', L.src_auto, L.src_auto_tip]);
    if (c.platen) opts.push(['platen', L.src_platen]);
    if (c.adf) opts.push(['adf', L.src_adf]);
    segFill(src, 'source', opts, keep);
  }
  function notes() {
    var c = cur(), s = val('source');
    fmtnote.hidden = !(val('fmt') === 'jpeg' && c.adf && s !== 'platen');
  }
  function fill() {
    var keep = +val('dpi') || 300, list = dpis(val('source'));
    var pick = list.indexOf(keep) >= 0 ? keep : list.indexOf(300) >= 0 ? 300 : list[0];
    segFill(dpi, 'dpi', list.map(function (r) { return [r, r + ' dpi']; }), pick);
    var glass = ((cur().platen || {}).dpi || []), top = glass.length ? Math.max.apply(null, glass) : 0;
    note.textContent = val('source') !== 'platen' && top && list.length && top > Math.max.apply(null, list) ? fmtL(L.glass_dpi, {n: top}) : '';
    notes();
  }
  sc.addEventListener('change', function () { sources(); fill(); });
  sources();
  src.addEventListener('change', fill); fill();
  Array.prototype.forEach.call(f.querySelectorAll('input[name=fmt]'), function (r) { r.addEventListener('change', function () { handle = null; if (where) where.textContent = ''; notes(); }); });
  function ext() { return val('fmt') === 'pdf' ? 'pdf' : 'jpg'; }
  function picker() {
    var e = ext();
    return window.showSaveFilePicker({suggestedName: (name.value || L.default_name) + '.' + e,
      types: [{description: e.toUpperCase(), accept: e === 'pdf' ? {'application/pdf': ['.pdf']} : {'image/jpeg': ['.jpg'], 'application/zip': ['.zip']}}]});
  }
  if (canPick) {  // where the browser lets you choose the folder, a button for it (the chooser also opens at "Scan" if you did not)
    document.getElementById('whererow').hidden = false;
    document.getElementById('pickbtn').addEventListener('click', function () {
      picker().then(function (h) { handle = h; where.textContent = h.name; }).catch(function () {});
    });
  }
  function finish() { go.disabled = false; wait.style.display = 'none'; }
  if (D.running > 0) { go.disabled = true; go.title = L.busy; }
  if (D.running > 0 && !window.__pending) setTimeout(function () { location.reload(); }, 3000);  // come back later: still there
  function save(sid, h) {
    return fetch('/me/scan/' + sid + '/file', {credentials: 'same-origin'}).then(function (r) { return r.blob().then(function (blob) {
      var m = /filename\*=UTF-8''([^;]+)/.exec(r.headers.get('Content-Disposition') || ''), nm = m ? decodeURIComponent(m[1]) : L.default_name;
      if (h) return h.createWritable().then(function (w) { return w.write(blob).then(function () { return w.close(); }); })
        .then(function () { sessionStorage.setItem('scan-saved', fmtL(L.saved, {name: h.name})); });
      var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = nm; document.body.appendChild(a); a.click(); a.remove();
      sessionStorage.setItem('scan-saved', fmtL(L.downloaded, {name: nm}));
    }); });
  }
  try { var was = sessionStorage.getItem('scan-saved'); if (was) { sessionStorage.removeItem('scan-saved'); say(was); } } catch (x) {}
  function poll(sid, h) {
    fetch('/me/scan/' + sid, {credentials: 'same-origin'}).then(function (r) { return r.json(); }).then(function (j) {
      if (j.state === 'running') return setTimeout(function () { poll(sid, h); }, 2000);
      window.__pending = false;
      if (j.state === 'done') return save(sid, h).then(function () { location.reload(); });
      location.reload();  // the error message is shown by the page next to it
    }).catch(function () { setTimeout(function () { poll(sid, h); }, 4000); });
  }
  f.addEventListener('submit', async function (ev) {
    if (!window.fetch) return;  // old browser: plain form post, the result is listed next to the form
    ev.preventDefault();
    go.disabled = true; wait.style.display = 'block'; say('');
    var h = handle;
    if (canPick && !h) {  // must be asked now: the permission is tied to this click, the scan takes much longer
      try { h = await picker(); } catch (x) { finish(); return; }  // user closed the dialog
    }
    try {
      var r = await fetch('/me/scan', {method: 'POST', body: new URLSearchParams(new FormData(f)), headers: {'X-Requested-With': 'fetch'}, credentials: 'same-origin'});
      var j = await r.json();
      if (!r.ok) { say(j.error || L.error); finish(); return; }
      window.__pending = true;
      poll(j.id, h);
    } catch (x) { say(L.error + ': ' + x); finish(); }
  });
})();
