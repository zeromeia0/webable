/**
 * Notes floating button + panel (uses /api/notes when logged in).
 */
(function () {
  var fab = document.getElementById('globalNotesFab');
  var panel = document.getElementById('globalNotesPanel');
  var closeBtn = document.getElementById('globalNotesClose');
  var listEl = document.getElementById('globalNotesList');
  var form = document.getElementById('globalNotesForm');
  var input = document.getElementById('globalNotesInput');
  if (!fab || !panel) return;

  function closeOthers() {
    ['globalCalcPanel', 'globalAiPanel', 'globalQuickAddPanel', 'globalExpensesPanel'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });
    ['globalCalcFab', 'globalAiFab', 'globalQuickAddFab', 'globalExpensesFab'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.setAttribute('aria-expanded', 'false');
    });
  }

  function openPanel() {
    closeOthers();
    panel.classList.remove('hidden');
    fab.setAttribute('aria-expanded', 'true');
    loadNotes();
    if (input) setTimeout(function () { input.focus(); }, 80);
  }

  function closePanel() {
    panel.classList.add('hidden');
    fab.setAttribute('aria-expanded', 'false');
  }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function renderNotes(notes) {
    if (!listEl) return;
    if (!notes || !notes.length) {
      listEl.innerHTML = '<p class="text-slate-500 text-xs">No notes yet.</p>';
      return;
    }
    listEl.innerHTML = notes
      .map(function (n) {
        var dt = (n.created_at || '').replace('T', ' ').slice(0, 16);
        return (
          '<div class="rounded-lg border border-slate-700 bg-slate-800/80 p-2.5 text-sm">' +
          '<p class="text-slate-200 whitespace-pre-wrap">' +
          escHtml(n.body) +
          '</p>' +
          '<div class="flex justify-between items-center mt-2 gap-2">' +
          '<span class="text-[10px] text-slate-500">' +
          escHtml(dt) +
          '</span>' +
          '<button type="button" class="text-red-400 text-xs hover:text-red-300" data-note-delete="' +
          n.id +
          '">Delete</button>' +
          '</div>' +
          '</div>'
        );
      })
      .join('');
    listEl.querySelectorAll('[data-note-delete]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-note-delete');
        fetch('/api/notes/' + id, { method: 'DELETE', credentials: 'same-origin' })
          .then(function () {
            loadNotes();
          })
          .catch(function () {});
      });
    });
  }

  function loadNotes() {
    fetch('/api/notes', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('notes');
        return r.json();
      })
      .then(function (data) {
        renderNotes(data.notes || []);
      })
      .catch(function () {
        if (listEl) listEl.innerHTML = '<p class="text-rose-300 text-xs">Could not load notes.</p>';
      });
  }

  fab.addEventListener('click', function () {
    if (panel.classList.contains('hidden')) openPanel();
    else closePanel();
  });
  if (closeBtn) closeBtn.addEventListener('click', closePanel);

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = (input && input.value) || '';
      if (!body.trim()) return;
      fetch('/api/notes', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ body: body.trim() }),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (res) {
          if (res.ok) {
            if (input) input.value = '';
            loadNotes();
          }
        })
        .catch(function () {});
    });
  }
})();
