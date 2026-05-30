/**
 * Preserve scroll position across full-page POST redirects on workspace pages.
 */
(function () {
  if (typeof window === 'undefined' || !window.sessionStorage) return;
  var path = window.location.pathname || '';
  if (path.indexOf('/instances/') !== 0) return;

  var KEY = 'wb-scroll:' + path + (window.location.search || '');

  function restoreScroll() {
    var raw = sessionStorage.getItem(KEY);
    if (raw === null) return;
    sessionStorage.removeItem(KEY);
    var y = parseInt(raw, 10);
    if (Number.isNaN(y)) return;
    requestAnimationFrame(function () {
      window.scrollTo(0, y);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var hash = window.location.hash;
    if (hash) {
      var target = document.querySelector(hash);
      if (target) {
        target.scrollIntoView({ block: 'start', behavior: 'auto' });
        return;
      }
    }
    restoreScroll();
  });

  document.querySelectorAll('form[method="post"]').forEach(function (form) {
    form.addEventListener('submit', function () {
      try {
        sessionStorage.setItem(KEY, String(window.scrollY || 0));
      } catch (e) { /* ignore */ }
    });
  });
})();
