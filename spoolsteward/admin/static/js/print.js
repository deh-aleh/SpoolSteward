// print.html
(function () {
  var D = JSON.parse(document.getElementById('pt-data').textContent);  // values from the server
  var f = document.getElementById('file'), go = document.getElementById('go'), drop = document.getElementById('drop');
  if (!f) return;
  var qs = D.queues, media = document.getElementById('media'), orient = document.querySelectorAll('input[name=orientation]');
  function chosenQueue() { return document.querySelector('input[name=queue]:checked') || document.querySelector('input[type=hidden][name=queue]'); }
  function reset(name) { var r = document.querySelector('input[name=' + name + '][value=""]'); if (r) r.checked = true; var s = document.querySelector('select[name=' + name + ']'); if (s) s.value = ''; }  // back to "same as printer"
  function show(id, on) { var e = document.getElementById(id); if (e) e.style.display = on ? '' : 'none'; }
  // the sheet takes the shape of the paper: a format of the printer (from its name, "…_210x297mm" or "…_8.5x11in"), turned when landscape
  function ratio() {
    var m = media.value, q = chosenQueue(), info = qs[q && q.value] || {}, id = m || info.media_default || '';
    var d = /_(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(mm|in)$/.exec(id), w = 210, h = 297;
    if (d) { w = parseFloat(d[1]); h = parseFloat(d[2]); }
    var o = document.querySelector('input[name=orientation]:checked');
    if (o && o.value === 'landscape') { var t = w; w = h; h = t; } else if (o && o.value === 'portrait' && w > h) { var t2 = w; w = h; h = t2; }
    drop.style.setProperty('--ratio', w + ' / ' + h);
  }
  function opts() {
    var r = chosenQueue(), q = r && qs[r.value] || {media: [], color: false};
    media.innerHTML = '<option value="">' + D.t_default + '</option>';
    q.media.forEach(function (m) {
      var o = document.createElement('option'); o.value = m.id; o.textContent = m.label + (m.id === q.media_default ? ' ' + D.t_default_mark : '');
      media.appendChild(o);
    });
    show('colorrow', q.color);
    if (!q.color) reset('color');
    show('sidesrow', q.duplex);  // only a printer with a duplex unit offers the choice
    if (!q.duplex) reset('sides');
    ratio();
  }
  Array.prototype.forEach.call(document.querySelectorAll('input[name=queue]'), function (r) { r.addEventListener('change', opts); });
  media.addEventListener('change', ratio);
  Array.prototype.forEach.call(orient, function (r) { r.addEventListener('change', ratio); });
  opts();
  function size(n) { return n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
  function upd() {
    var x = f.files && f.files[0];
    document.querySelector('.drop .empty').hidden = !!x; document.getElementById('filled').hidden = !x;
    if (x) { document.getElementById('fname').textContent = x.name; document.getElementById('fsize').textContent = size(x.size); }
  }
  f.addEventListener('change', upd);
  ['dragenter', 'dragover'].forEach(function (e) { drop.addEventListener(e, function (ev) { ev.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (e) { drop.addEventListener(e, function (ev) { ev.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (ev) { if (ev.dataTransfer.files.length) { f.files = ev.dataTransfer.files; upd(); } });
  document.getElementById('pf').addEventListener('submit', function () { go.disabled = true; document.getElementById('golabel').textContent = D.t_sending; });
  upd();
})();
