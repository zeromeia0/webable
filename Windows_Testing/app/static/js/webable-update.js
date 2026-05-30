/**
 * Update UI: deployment-aware modal, async orchestration polling, one-click apply.
 */
(function () {
  var STORAGE_KEY = 'webable_update_ack_sha';
  var modal;
  var pollTimer;
  var applyFailed = false;
  var caps = {};
  var lastOrchestration = {};

  function getAckedSha() {
    try {
      return localStorage.getItem(STORAGE_KEY) || '';
    } catch (e) {
      return '';
    }
  }

  function setAckedSha(sha) {
    try {
      if (sha) localStorage.setItem(STORAGE_KEY, sha);
    } catch (e) { /* ignore */ }
  }

  function trapEscape(e) {
    if (!modal || modal.classList.contains('hidden')) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  function showModal() {
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.addEventListener('keydown', trapEscape, true);
    var btn = document.getElementById('wbUpdateGotIt');
    if (btn) setTimeout(function () {
      btn.focus();
    }, 80);
  }

  function hideModal() {
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.removeEventListener('keydown', trapEscape, true);
    stopPoll();
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function renderNotes(html) {
    var body = document.getElementById('wbUpdateBody');
    if (!body) return;
    body.innerHTML = html || '<p class="text-slate-500 text-sm">No release notes available.</p>';
  }

  function setPrimaryLoading(loading) {
    var btn = document.getElementById('wbUpdateGotIt');
    if (!btn) return;
    btn.disabled = !!loading;
    btn.classList.toggle('opacity-60', !!loading);
    btn.classList.toggle('cursor-wait', !!loading);
  }

  function wirePrimary(handler, label) {
    var btn = document.getElementById('wbUpdateGotIt');
    if (!btn) return;
    btn.replaceWith(btn.cloneNode(true));
    btn = document.getElementById('wbUpdateGotIt');
    if (label) btn.textContent = label;
    btn.addEventListener('click', handler);
  }

  function wireDismiss(handler) {
    var btn = document.getElementById('wbUpdateDismiss');
    if (!btn) return;
    btn.replaceWith(btn.cloneNode(true));
    btn = document.getElementById('wbUpdateDismiss');
    btn.addEventListener('click', handler);
  }

  function setProgressVisible(vis, text) {
    var wrap = document.getElementById('wbUpdateProgress');
    var tx = document.getElementById('wbUpdateProgressText');
    if (!wrap || !tx) return;
    if (vis) {
      wrap.classList.remove('hidden');
      tx.textContent = text || '';
    } else {
      wrap.classList.add('hidden');
    }
  }

  function orchestrationLabel(phase) {
    var map = {
      idle: '',
      checking: 'Checking…',
      pulling: 'Pulling changes…',
      rebuilding: 'Rebuilding…',
      restarting: 'Restarting…',
      waiting_for_health: 'Waiting for app health…',
      reconnecting: 'Reconnecting…',
      completed: 'Completed',
      failed: 'Failed'
    };
    return map[phase] || phase || '';
  }

  function pollStatusOnce() {
    return fetch('/api/update/status', { credentials: 'same-origin' })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      });
  }

  function applyOrchestrationUI(orch) {
    if (!orch) return;
    lastOrchestration = orch;
    var phase = orch.phase || 'idle';
    var msg = orch.message || '';
    var err = orch.error;
    if (phase !== 'idle' && phase !== 'completed' && phase !== 'failed') {
      setProgressVisible(true, orchestrationLabel(phase) + (msg ? ' — ' + msg : ''));
      setPrimaryLoading(true);
    }
    if (phase === 'failed') {
      setProgressVisible(true, 'Error: ' + (err || msg || 'unknown'));
      setPrimaryLoading(false);
      var sub = document.getElementById('wbUpdateSubtitle');
      if (sub) {
        sub.textContent = err || msg || 'Update failed.';
        sub.classList.remove('hidden');
      }
      wirePrimary(function () {
        applyFailed = true;
        dismissWithAck(true);
      }, 'Dismiss');
      return;
    }
    if (phase === 'completed') {
      stopPoll();
      setProgressVisible(true, msg || 'Completed.');
      setPrimaryLoading(false);
      var remote = (window.__WB_UPDATE_REMOTE__ || '').trim();
      if (remote) setAckedSha(remote);
      var subDone = document.getElementById('wbUpdateSubtitle');
      if (subDone) {
        subDone.textContent = orch.restart_required
          ? 'Reload the page to load the new version.'
          : 'Reload the page to refresh.';
        subDone.classList.remove('hidden');
      }
      wirePrimary(function () {
        window.location.reload();
      }, 'Reload app');
      return;
    }
  }

  function startPolling() {
    stopPoll();
    pollTimer = setInterval(function () {
      pollStatusOnce().then(function (res) {
        if (!res || !res.j) return;
        var o = res.j.orchestration;
        if (o) applyOrchestrationUI(o);
        caps = res.j.capabilities || caps;
      }).catch(function () { /* ignore */ });
    }, 1600);
  }

  function postUpdateStart() {
    setPrimaryLoading(true);
    setProgressVisible(true, 'Starting…');
    startPolling();
    return fetch('/api/update/start', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: '{}'
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, status: r.status, j: j };
        });
      })
      .then(function (res) {
        var j = res.j || {};
        if (res.status === 401 && j.auth_required) {
          var sub = document.getElementById('wbUpdateSubtitle');
          if (sub) {
            sub.textContent = 'Sign in to apply this update, then try again.';
            sub.classList.remove('hidden');
          }
          setPrimaryLoading(false);
          stopPoll();
          return;
        }
        if (!res.ok || !j.success) {
          setPrimaryLoading(false);
          stopPoll();
          var s2 = document.getElementById('wbUpdateSubtitle');
          if (s2) {
            s2.textContent = j.message || 'Could not start update.';
            s2.classList.remove('hidden');
          }
          return;
        }
        pollStatusOnce().then(function (r2) {
          if (r2 && r2.j && r2.j.orchestration) applyOrchestrationUI(r2.j.orchestration);
        });
      })
      .catch(function () {
        setPrimaryLoading(false);
        stopPoll();
      });
  }

  function dismissWithAck(force) {
    var remote = (window.__WB_UPDATE_REMOTE__ || '').trim();
    fetch('/api/update/got-it', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ remote_sha: remote, force_acknowledge: !!force })
    })
      .then(function () {
        if (remote) setAckedSha(remote);
        hideModal();
      })
      .catch(function () {
        hideModal();
      });
  }

  function onApplyClick() {
    postUpdateStart();
  }

  function deploymentHint() {
    var mode = caps.deployment_mode || '';
    var ext = caps.watchtower_expected;
    var action = caps.update_action_mode;
    if (mode === 'image' && action === 'external_only') {
      var t = 'This instance runs from a container image.';
      if (ext) t += ' Updates are expected from an external updater (for example Watchtower) or your platform.';
      else t += ' Install updates by pulling a new image or running compose on the host.';
      return t;
    }
    if (mode === 'git') {
      return 'Git deployment: updates apply to this server\'s working tree when enabled.';
    }
    if (mode === 'image' && action === 'docker_compose') {
      return 'Image deployment: one-click update runs docker compose pull and up on the host (requires socket access).';
    }
    return '';
  }

  function setDeployBadge(data) {
    var c = data.capabilities || data;
    var el = document.getElementById('wbDeployBadge');
    if (!el || !c || !c.deployment_mode) return;
    el.classList.remove('hidden');
    var t = c.deployment_mode === 'git' ? 'Git deploy' : 'Image deploy';
    if (c.watchtower_expected) t += ' · external';
    el.textContent = t;
    el.title =
      c.deployment_mode === 'image' && c.update_action_mode === 'external_only'
        ? 'Updates are managed outside the app (e.g. Watchtower or your platform).'
        : c.deployment_mode === 'git'
          ? 'Self-hosted git deployment.'
          : 'Compose-based image updates may be available from this UI when enabled.';
  }

  function maybeShowFromStatus(data) {
    if (!data) return;
    caps = data.capabilities || {};
    setDeployBadge(data);
    var orch = data.orchestration;
    if (orch && orch.phase && orch.phase !== 'idle' && orch.phase !== 'completed' && orch.phase !== 'failed') {
      showModal();
      applyOrchestrationUI(orch);
      startPolling();
      var d2 = document.getElementById('wbUpdateDismiss');
      if (d2) {
        d2.classList.remove('hidden');
        d2.textContent = 'Not now';
        wireDismiss(function () {
          stopPoll();
          dismissWithAck(true);
        });
      }
      wirePrimary(onApplyClick, 'Apply update');
      return;
    }
    if (!data.update_available) return;
    if (!data.remote_sha) return;
    window.__WB_UPDATE_REMOTE__ = data.remote_sha;
    if (getAckedSha() === data.remote_sha && !applyFailed) return;

    var title = document.getElementById('wbUpdateTitle');
    if (title) title.textContent = 'Application update';
    var sub = document.getElementById('wbUpdateSubtitle');
    var hint = deploymentHint();
    if (sub) {
      sub.textContent = hint || 'A new version is available. Review the notes below.';
      sub.classList.remove('hidden');
    }
    var wrap = document.getElementById('wbUpdateScroll');
    if (wrap) wrap.classList.remove('hidden');
    renderNotes(data.update_md_html);
    applyFailed = false;

    var dismiss = document.getElementById('wbUpdateDismiss');
    var supported = !!caps.update_action_supported;

    if (dismiss) {
      if (supported) {
        dismiss.classList.remove('hidden');
        dismiss.textContent = 'Not now';
      } else {
        dismiss.classList.add('hidden');
      }
    }

    if (supported) {
      wirePrimary(onApplyClick, caps.deployment_mode === 'image' ? 'Update now' : 'Apply update');
      wireDismiss(function () {
        dismissWithAck(true);
      });
    } else {
      wirePrimary(function () {
        dismissWithAck(true);
      }, caps.watchtower_expected ? 'OK' : 'Acknowledge');
    }
    showModal();
  }

  function init() {
    modal = document.getElementById('wbUpdateModal');
    if (!modal) return;
    fetch('/api/update/status', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('status');
        return r.json();
      })
      .then(maybeShowFromStatus)
      .catch(function () { /* offline */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
