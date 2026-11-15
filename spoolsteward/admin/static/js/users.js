// user_new.html: a RADIUS account has no password here and no admin box
(function () {
  var f = document.getElementById('newuser'); if (!f) return;
  var radios = f.querySelectorAll('input[name=kind]');
  function update() {
    var radius = Array.prototype.some.call(radios, function (r) { return r.checked && r.value === 'radius'; });
    f.querySelectorAll('[data-local]').forEach(function (e) { e.hidden = radius; });
  }
  Array.prototype.forEach.call(radios, function (r) { r.addEventListener('change', update); });
  update();
})();
