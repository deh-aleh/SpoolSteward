// The registration switch: off -> a window to choose how to open it; on -> the form posts "off" by itself
(function () {
  var sw = document.getElementById('reg-switch'), dlg = document.getElementById('reg-dlg');
  if (!sw || !dlg || !dlg.showModal) return;
  sw.addEventListener('click', function (e) {
    if (sw.getAttribute('aria-checked') === 'true') return;
    e.preventDefault();
    dlg.showModal();
  });
  document.getElementById('reg-cancel').addEventListener('click', function () { dlg.close(); });
})();
