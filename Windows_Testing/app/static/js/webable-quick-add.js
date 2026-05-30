(function () {
  var fab = document.getElementById('globalQuickAddFab');
  var panel = document.getElementById('globalQuickAddPanel');
  var closeBtn = document.getElementById('globalQuickAddClose');
  var dateInput = document.getElementById('qaDate');
  var catWrap = document.getElementById('qaCategoryWrap');
  if (!fab || !panel) return;

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function closeOthers() {
    ['globalCalcPanel', 'globalAiPanel', 'globalNotesPanel', 'globalExpensesPanel'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });
    ['globalCalcFab', 'globalAiFab', 'globalNotesFab', 'globalExpensesFab'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.setAttribute('aria-expanded', 'false');
    });
  }

  function syncCategory() {
    if (!catWrap) return;
    var expense = panel.querySelector('input[name="txn_type"][value="expense"]');
    catWrap.classList.toggle('hidden', !(expense && expense.checked));
  }

  function openPanel() {
    closeOthers();
    panel.classList.remove('hidden');
    fab.setAttribute('aria-expanded', 'true');
    if (dateInput && !dateInput.value) dateInput.value = todayIso();
    syncCategory();
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

  panel.querySelectorAll('input[name="txn_type"]').forEach(function (r) {
    r.addEventListener('change', syncCategory);
  });
  syncCategory();
})();
