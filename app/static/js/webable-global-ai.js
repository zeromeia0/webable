/**
 * Global AI assistant floating panel.
 */
(function (global) {
  'use strict';

  function init() {
    var fab = document.getElementById('globalAiFab');
    var panel = document.getElementById('globalAiPanel');
    var messages = document.getElementById('globalAiMessages');
    var form = document.getElementById('globalAiForm');
    var questionInput = document.getElementById('globalAiQuestion');
    if (!fab || !panel || !form || !messages) return;

    var instanceId = global.__WEBABLE_FAB_INSTANCE_ID;

    function addMessage(role, text) {
      var wrapper = document.createElement('div');
      wrapper.className =
        role === 'assistant'
          ? 'bg-slate-800 rounded-xl p-3 whitespace-pre-wrap'
          : 'bg-indigo-500/20 border border-indigo-500/40 rounded-xl p-3 whitespace-pre-wrap';
      wrapper.textContent = text;
      messages.appendChild(wrapper);
      messages.scrollTop = messages.scrollHeight;
    }

    fab.addEventListener('click', function () {
      var opening = panel.classList.contains('hidden');
      if (opening) {
        ['globalCalcPanel', 'globalQuickAddPanel', 'globalNotesPanel', 'globalExpensesPanel'].forEach(function (id) {
          var el = document.getElementById(id);
          if (el) el.classList.add('hidden');
        });
        ['globalCalcFab', 'globalQuickAddFab', 'globalNotesFab', 'globalExpensesFab'].forEach(function (id) {
          var el = document.getElementById(id);
          if (el) el.setAttribute('aria-expanded', 'false');
        });
      }
      panel.classList.toggle('hidden');
      var open = !panel.classList.contains('hidden');
      fab.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = (questionInput.value || '').trim();
      if (!q) return;
      addMessage('user', q);
      questionInput.value = '';
      var fd = new FormData();
      fd.append('question', q);
      if (instanceId != null) fd.append('instance_id', String(instanceId));
      fetch('/ai/global', { method: 'POST', body: fd, credentials: 'same-origin' })
        .then(function (res) {
          return res.json().then(function (data) {
            return { res: res, data: data };
          });
        })
        .then(function (out) {
          if (!out.res.ok) throw new Error(out.data.error || 'failed');
          addMessage('assistant', out.data.answer || 'No answer returned.');
        })
        .catch(function () {
          addMessage(
            'assistant',
            "I couldn't connect to the local AI assistant. Make sure Ollama is running and the qwen2.5-coder:3b model is installed."
          );
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(typeof window !== 'undefined' ? window : globalThis);
