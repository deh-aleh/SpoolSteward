// the form of a new backup: only the part of the chosen encryption is shown
function bk() {
  var c = document.querySelector('input[name=mode]:checked'); if (!c) return;
  ['passphrase', 'key', 'none'].forEach(function (k) { document.getElementById('m-' + k).hidden = (k !== c.value); });
}
document.querySelectorAll('input[name=mode]').forEach(function (r) { r.addEventListener('change', bk); });
bk();
