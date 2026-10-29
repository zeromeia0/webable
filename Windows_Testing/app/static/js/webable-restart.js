/**
 * Top bar "Restart server" button. Queues a rebuild for the host-side helper
 * (scripts/webable-restart-watcher.sh), then waits until a new server process answers
 * (different boot_id) and reloads the page.
 */
(function () {
  var btn = document.getElementById('wbRestartServerBtn');
  var msg = document.getElementById('wbRestartServerMsg');
  if (!btn || btn._wbInit) return;
  btn._wbInit = true;

  var POLL_MS = 2000;
  var TIMEOUT_MS = 15 * 60 * 1000;
  var bootId = null;
  var polling = false;
  var startedAt = 0;
  var sawDown = false;

  function say(text, tone) {
    msg.textContent = text || '';
    msg.title = text || '';
    msg.className = 'text-[11px] max-w-[22rem] truncate ' +
      ({ err: 'text-rose-300', ok: 'text-emerald-300', busy: 'text-amber-200' }[tone] || 'text-slate-400') +
      (text ? '' : ' hidden');
  }

  function busy(on) {
    btn.disabled = on;
    btn.textContent = on ? '↻ Restarting…' : '↻ Restart server';
  }

  function getStatus() {
    return fetch('/api/server/restart/status', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('status ' + r.status);
      return r.json();
    });
  }

  function poll() {
    if (!polling) return;
    if (Date.now() - startedAt > TIMEOUT_MS) {
      polling = false;
      busy(false);
      say('Restart is taking unusually long — check: sudo journalctl -u webable-restart-helper', 'err');
      return;
    }
    getStatus().then(function (st) {
      if (bootId && st.boot_id !== bootId) {
        say('Server restarted — reloading…', 'ok');
        setTimeout(function () { location.reload(); }, 600);
        polling = false;
        return;
      }
      if (st.state === 'failed') {
        polling = false;
        busy(false);
        say('Rebuild failed: ' + (st.message || 'see the helper log') + (st.log_tail ? ' — ' + st.log_tail.split('\n').filter(Boolean).slice(-1)[0] : ''), 'err');
        return;
      }
      if (st.state === 'running') say(sawDown ? 'Starting new server…' : 'Rebuilding image… (the page reloads when done)', 'busy');
      else if (st.pending) say('Waiting for the restart helper to pick up the request…', 'busy');
      setTimeout(poll, POLL_MS);
    }).catch(function () {
      // Expected while the old container stops and the new one boots.
      sawDown = true;
      say('Server is restarting…', 'busy');
      setTimeout(poll, POLL_MS);
    });
  }

  function startPolling() {
    if (polling) return;
    polling = true;
    startedAt = Date.now();
    sawDown = false;
    busy(true);
    poll();
  }

  btn.addEventListener('click', function () {
    if (!confirm('Rebuild the app from the current code and restart the server? The page will reload when it is back (usually under a minute).')) return;
    busy(true);
    say('Requesting restart…', 'busy');
    fetch('/api/server/restart', { method: 'POST', credentials: 'same-origin' })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) throw new Error(d.detail || ('Request failed (' + r.status + ')'));
          return d;
        });
      })
      .then(function (st) {
        bootId = bootId || st.boot_id;
        startPolling();
      })
      .catch(function (err) {
        busy(false);
        say(err.message, 'err');
      });
  });

  // Remember which server process rendered this page; resume if a restart is already under way.
  getStatus().then(function (st) {
    bootId = st.boot_id;
    if (st.pending || st.state === 'running') startPolling();
  }).catch(function () { /* not logged in or older server */ });
})();
