/**
 * Global AI assistant floating panel.
 */
(function (global) {
  'use strict';

  var MSG_AUTH =
    'AI is not available right now. Make sure Ollama is running and signed in.';
  var MSG_UNREACHABLE = 'AI is not available right now. Make sure Ollama is running.';
  var DEFAULT_MODEL = 'minimax-m2.5:cloud';

  function init() {
    var fab = document.getElementById('globalAiFab');
    var panel = document.getElementById('globalAiPanel');
    var messages = document.getElementById('globalAiMessages');
    var form = document.getElementById('globalAiForm');
    var questionInput = document.getElementById('globalAiQuestion');
    var signinModal = document.getElementById('globalAiSigninModal');
    if (!fab || !panel || !form || !messages) return;

    var instanceId = global.__WEBABLE_FAB_INSTANCE_ID;

    function ensureSigninModal() {
      if (signinModal) return signinModal;
      var root = document.getElementById('webableFabRoot') || document.body;
      var el = document.createElement('div');
      el.id = 'globalAiSigninModal';
      el.className = 'webable-ai-signin-modal hidden';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      el.setAttribute('aria-labelledby', 'globalAiSigninTitle');
      el.innerHTML =
        '<div class="webable-ai-signin-backdrop" data-close-signin></div>' +
        '<div class="webable-ai-signin-card">' +
        '<h3 id="globalAiSigninTitle" class="text-base font-semibold mb-2">Ollama sign-in required</h3>' +
        '<p id="globalAiSigninIntro" class="text-sm text-slate-300 mb-3"></p>' +
        '<p class="text-xs text-slate-400 mb-1">Run:</p>' +
        '<pre id="globalAiSigninCmd" class="webable-ai-signin-cmd mb-3"></pre>' +
        '<p class="text-xs text-slate-400 mb-1">Then test:</p>' +
        '<pre id="globalAiSigninTestCmd" class="webable-ai-signin-cmd mb-3"></pre>' +
        '<p id="globalAiSigninFooter" class="text-sm text-slate-400 mb-4"></p>' +
        '<button type="button" class="w-full py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm" data-close-signin>Close</button>' +
        '</div>';
      root.appendChild(el);
      el.querySelectorAll('[data-close-signin]').forEach(function (node) {
        node.addEventListener('click', function () {
          el.classList.add('hidden');
        });
      });
      signinModal = el;
      return el;
    }

    function fillSigninModal(modal, signedIn, instructions) {
      var intro = modal.querySelector('#globalAiSigninIntro');
      var cmd = modal.querySelector('#globalAiSigninCmd');
      var testCmd = modal.querySelector('#globalAiSigninTestCmd');
      var footer = modal.querySelector('#globalAiSigninFooter');
      var title = modal.querySelector('#globalAiSigninTitle');
      instructions = instructions || {};
      if (title && instructions.title) title.textContent = instructions.title;
      if (intro) {
        intro.textContent =
          instructions.intro ||
          'To use Webable AI with ' +
            DEFAULT_MODEL +
            ', sign in to Ollama Cloud after the containers are running.';
      }
      if (cmd) cmd.textContent = instructions.signin_cmd || 'sudo docker exec -it webable-ollama ollama signin';
      if (testCmd) {
        testCmd.textContent = instructions.test_cmd || 'sudo docker exec -it webable-ollama ollama run ' + DEFAULT_MODEL;
      }
      if (footer) {
        footer.textContent = signedIn
          ? 'Ollama reports you are already signed in. Try your AI message again.'
          : instructions.footer || 'After signing in, come back and try your AI message again.';
      }
    }

    function openSigninModal(signedIn, instructions) {
      var modal = ensureSigninModal();
      fillSigninModal(modal, !!signedIn, instructions);
      modal.classList.remove('hidden');
    }

    function onSigninLinkClick(e) {
      e.preventDefault();
      fetch('/api/ai/ollama/signin-link', { credentials: 'same-origin' })
        .then(function (res) {
          return res.json().then(function (data) {
            return { res: res, data: data };
          });
        })
        .then(function (out) {
          if (out.data && out.data.signin_url) {
            global.open(out.data.signin_url, '_blank', 'noopener,noreferrer');
            return;
          }
          if (out.data && out.data.signed_in) {
            addMessage('assistant', 'Ollama is already signed in. Try your message again.');
            return;
          }
          openSigninModal(false, (out.data && out.data.instructions) || null);
        })
        .catch(function () {
          openSigninModal(false, null);
        });
    }

    function addMessage(role, text, opts) {
      opts = opts || {};
      var wrapper = document.createElement('div');
      wrapper.className =
        role === 'assistant'
          ? 'bg-slate-800 rounded-xl p-3 text-sm leading-relaxed'
          : 'bg-indigo-500/20 border border-indigo-500/40 rounded-xl p-3 whitespace-pre-wrap text-sm';
      if (opts.html) {
        wrapper.innerHTML = opts.html;
        var link = wrapper.querySelector('.wb-ai-signin-link');
        if (link) link.addEventListener('click', onSigninLinkClick);
      } else {
        wrapper.textContent = text;
      }
      messages.appendChild(wrapper);
      messages.scrollTop = messages.scrollHeight;
    }

    function addUnavailableMessage(data) {
      var reason = data && data.reason;
      var canSignin = data && data.can_signin;
      var signinUrl = data && data.signin_url;

      if (reason === 'ollama_unreachable') {
        addMessage('assistant', (data && data.error) || MSG_UNREACHABLE);
        return;
      }

      if (canSignin || reason === 'ollama_auth_required') {
        var html =
          'AI is not available right now. Make sure Ollama is running and ' +
          '<button type="button" class="wb-ai-signin-link">signed in</button>.';
        addMessage('assistant', '', { html: html });
        if (signinUrl) {
          var note = document.createElement('p');
          note.className = 'text-xs text-slate-400 mt-2';
          var a = document.createElement('a');
          a.href = signinUrl;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.className = 'text-violet-300 hover:underline';
          a.textContent = 'Open Ollama sign-in';
          a.addEventListener('click', function (ev) {
            ev.preventDefault();
            global.open(signinUrl, '_blank', 'noopener,noreferrer');
          });
          note.appendChild(a);
          messages.lastChild.appendChild(note);
        }
        return;
      }

      addMessage('assistant', (data && data.error) || MSG_AUTH);
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
          if (!out.res.ok) {
            addUnavailableMessage(out.data);
            return;
          }
          addMessage('assistant', out.data.answer || 'No answer returned.');
        })
        .catch(function () {
          addUnavailableMessage({
            reason: 'ollama_unreachable',
            can_signin: false,
            error: MSG_UNREACHABLE,
          });
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(typeof window !== 'undefined' ? window : globalThis);
