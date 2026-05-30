/** Dashboard: expense entries expand/collapse with localStorage. */
(function () {
  var STORAGE_KEY = 'webable_expense_entries_expanded';

  function readExpanded() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (v === '0' || v === 'false') return false;
      if (v === '1' || v === 'true') return true;
    } catch (e) { /* ignore */ }
    return true;
  }

  function writeExpanded(open) {
    try {
      localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
    } catch (e) { /* ignore */ }
  }

  function applyState(open) {
    var btn = document.getElementById('wbExpenseToggle');
    var body = document.getElementById('wbExpenseBody');
    var chevron = document.getElementById('wbExpenseChevron');
    if (!btn || !body) return;
    var label = document.getElementById('wbExpenseToggleLabel');
    if (open) {
      body.classList.remove('hidden');
      if (label) label.textContent = 'Hide expenses';
      else btn.textContent = 'Hide expenses';
      btn.setAttribute('aria-expanded', 'true');
      if (chevron) chevron.textContent = '▲';
    } else {
      body.classList.add('hidden');
      if (label) label.textContent = 'Show expenses';
      else btn.textContent = 'Show expenses';
      btn.setAttribute('aria-expanded', 'false');
      if (chevron) chevron.textContent = '▼';
    }
  }

  function init() {
    var btn = document.getElementById('wbExpenseToggle');
    if (!btn) return;
    var open = readExpanded();
    applyState(open);
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var next = btn.getAttribute('aria-expanded') !== 'true';
      writeExpanded(next);
      applyState(next);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
