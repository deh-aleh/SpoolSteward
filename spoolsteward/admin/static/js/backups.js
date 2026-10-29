/* The explanation under the title is a drop-down on a phone (closed: less scrolling) and plain text on a wide screen. */
(function () {
  var d = document.querySelector('details.bk-intro'), wide = window.matchMedia('(min-width:701px)');
  if (!d) return;
  function fit() { d.classList.toggle('bk-plain', wide.matches); if (wide.matches) d.open = true; }
  fit();
  if (wide.addEventListener) wide.addEventListener('change', fit);
})();
function bk(){var m=document.querySelector('input[name=mode]:checked').value;
  ['passphrase','key','none'].forEach(function(k){document.getElementById('m-'+k).hidden=(k!==m)})}
document.querySelectorAll('input[name=mode]').forEach(function (r) { r.addEventListener('change', bk); });
bk();
