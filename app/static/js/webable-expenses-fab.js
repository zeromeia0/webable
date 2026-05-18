/**
 * Floating Expenses panel (dashboard data via window.__WEBABLE_EXPENSE_PANEL__).
 */
(function () {
  var fab = document.getElementById('globalExpensesFab');
  var panel = document.getElementById('globalExpensesPanel');
  var list = document.getElementById('globalExpensesList');
  var summary = document.getElementById('globalExpensesSummary');
  var closeBtn = document.getElementById('globalExpensesClose');
  if (!fab || !panel) return;

  var data = window.__WEBABLE_EXPENSE_PANEL__;
  if (!data || !data.entries) {
    return;
  }
  fab.classList.remove('hidden');

  function fmtMoney(n) {
    if (window.WebableCurrency && window.WebableCurrency.format) {
      return window.WebableCurrency.format(n);
    }
    return 'EUR ' + Number(n).toFixed(2);
  }

  function closeOthers() {
    ['globalQuickAddPanel', 'globalCalcPanel', 'globalAiPanel', 'globalNotesPanel'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });
    ['globalQuickAddFab', 'globalCalcFab', 'globalAiFab', 'globalNotesFab'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.setAttribute('aria-expanded', 'false');
    });
  }

  function renderList() {
    if (!list) return;
    var entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<p class="text-slate-500 text-sm">No expense entries yet.</p>';
      return;
    }
    list.innerHTML = '<ul class="space-y-2 text-sm">' + entries.map(function (row) {
      var ws = row.workspace ? ' <span class="text-slate-500 text-xs">(' + row.workspace + ')</span>' : '';
      return '<li class="flex flex-col gap-0.5 border-b border-slate-800 pb-2">' +
        '<span class="text-slate-200 truncate">' + (row.name || '') + ws + '</span>' +
        '<span class="text-rose-300 font-medium">' + fmtMoney(row.amount_eur) + '</span>' +
        '<span class="text-slate-400 text-xs">' + (row.pct_expenses_label || '') + ' · ' + (row.pct_income_label || '') + '</span>' +
        '</li>';
    }).join('') + '</ul>';
  }

  function openPanel() {
    closeOthers();
    renderList();
    if (summary && data.summary) summary.textContent = data.summary;
    panel.classList.remove('hidden');
    fab.setAttribute('aria-expanded', 'true');
    if (window.WebableCurrency && typeof window.WebableCurrency.apply === 'function') {
      window.WebableCurrency.apply(panel);
    }
  }

  function closePanel() {
    panel.classList.add('hidden');
    fab.setAttribute('aria-expanded', 'false');
  }

  fab.addEventListener('click', function () {
    if (panel.classList.contains('hidden')) openPanel();
    else closePanel();
  });
  if (closeBtn) closeBtn.addEventListener('click', closePanel);

  document.addEventListener('webable:currency', function () {
    if (!panel.classList.contains('hidden')) renderList();
  });
})();
