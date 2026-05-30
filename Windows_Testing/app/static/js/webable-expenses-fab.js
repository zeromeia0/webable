/**
 * Global floating Expenses panel — loads data from inline bootstrap or /api/expenses/panel.
 */
(function () {
  var fab = document.getElementById('globalExpensesFab');
  var panel = document.getElementById('globalExpensesPanel');
  var list = document.getElementById('globalExpensesList');
  var summary = document.getElementById('globalExpensesSummary');
  var closeBtn = document.getElementById('globalExpensesClose');
  if (!fab || !panel) return;

  var data = null;
  var loadPromise = null;
  var isOpen = false;

  panel.classList.add('hidden');
  fab.setAttribute('aria-expanded', 'false');

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

  function fetchPanelData() {
    if (window.__WEBABLE_EXPENSE_PANEL__) {
      return Promise.resolve(window.__WEBABLE_EXPENSE_PANEL__);
    }
    if (!loadPromise) {
      loadPromise = fetch('/api/expenses/panel', { credentials: 'same-origin' })
        .then(function (r) {
          if (r.status === 401) return null;
          if (!r.ok) throw new Error('expenses_panel');
          return r.json();
        })
        .catch(function () {
          return null;
        });
    }
    return loadPromise;
  }

  function renderList() {
    if (!list || !data) return;
    var entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<p class="text-slate-500 text-sm">No expense entries yet.</p>';
      return;
    }
    list.innerHTML =
      '<ul class="space-y-2 text-sm">' +
      entries
        .map(function (row) {
          var ws = row.workspace ? ' <span class="text-slate-500 text-xs">(' + row.workspace + ')</span>' : '';
          return (
            '<li class="flex flex-col gap-0.5 border-b border-slate-800 pb-2">' +
            '<span class="text-slate-200 truncate">' +
            (row.name || '') +
            ws +
            '</span>' +
            '<span class="text-rose-300 font-medium">' +
            fmtMoney(row.amount_eur) +
            '</span>' +
            '<span class="text-slate-400 text-xs">' +
            (row.pct_expenses_label || '') +
            ' · ' +
            (row.pct_income_label || '') +
            '</span>' +
            '</li>'
          );
        })
        .join('') +
      '</ul>';
  }

  function closePanel() {
    isOpen = false;
    panel.classList.add('hidden');
    fab.setAttribute('aria-expanded', 'false');
  }

  function openPanel() {
    fetchPanelData().then(function (payload) {
      if (!payload) return;
      data = payload;
      closeOthers();
      renderList();
      if (summary) summary.textContent = data.summary || '';
      panel.classList.remove('hidden');
      isOpen = true;
      fab.setAttribute('aria-expanded', 'true');
      if (window.WebableCurrency && typeof window.WebableCurrency.scanMoney === 'function') {
        window.WebableCurrency.scanMoney(panel);
      }
    });
  }

  fab.addEventListener('click', function (e) {
    e.stopPropagation();
    if (isOpen) closePanel();
    else openPanel();
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      closePanel();
    });
  }

  document.addEventListener('webable:currency', function () {
    if (isOpen) renderList();
  });

  fetchPanelData().then(function (payload) {
    if (payload) {
      data = payload;
      fab.classList.remove('hidden');
    } else {
      fab.classList.add('hidden');
    }
  });
})();
