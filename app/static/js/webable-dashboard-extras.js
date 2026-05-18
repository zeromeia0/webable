/** Expense list show/hide toggle on dashboard Mother insights. */
(function () {
  function init() {
    var btn = document.getElementById('wbExpenseToggle');
    var details = document.getElementById('wbExpenseDetails');
    if (!btn || !details) return;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var open = details.hasAttribute('open');
      if (open) {
        details.removeAttribute('open');
        btn.textContent = 'Show expenses';
        btn.setAttribute('aria-expanded', 'false');
      } else {
        details.setAttribute('open', 'open');
        btn.textContent = 'Hide expenses';
        btn.setAttribute('aria-expanded', 'true');
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
