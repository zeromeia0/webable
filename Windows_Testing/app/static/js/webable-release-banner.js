/**
 * After container or git updates: compare /api/build-info to last-seen build_id.
 * First visit records the current build without showing a banner.
 */
(function () {
  var STORAGE_KEY = 'webable_seen_build_id';
  var POLL_MS = 5 * 60 * 1000;

  function getSeen() {
    try {
      return localStorage.getItem(STORAGE_KEY) || '';
    } catch (e) {
      return '';
    }
  }

  function setSeen(id) {
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
    } catch (e) { /* ignore */ }
  }

  function setDeployBadge(data) {
    var el = document.getElementById('wbDeployBadge');
    if (!el || !data || !data.deployment_mode) return;
    el.classList.remove('hidden');
    var t = data.deployment_mode === 'git' ? 'Git deploy' : 'Image deploy';
    if (data.watchtower_expected) t += ' · external';
    el.textContent = t;
  }

  function apply(data) {
    var banner = document.getElementById('wbReleaseBanner');
    var textEl = document.getElementById('wbReleaseBannerText');
    var dismiss = document.getElementById('wbReleaseBannerDismiss');
    if (!banner || !textEl || !dismiss || !data || !data.build_id) return;

    setDeployBadge(data);

    var cur = String(data.build_id);
    var seen = getSeen();

    function hide() {
      banner.classList.add('hidden');
    }

    function show(msg) {
      textEl.textContent = msg;
      banner.classList.remove('hidden');
    }

    dismiss.onclick = function () {
      setSeen(cur);
      hide();
    };

    if (!seen) {
      setSeen(cur);
      hide();
      return;
    }
    if (seen !== cur) {
      var ver = data.version || '';
      var commit = (data.commit || '').slice(0, 7);
      var mode = data.deployment_mode || 'git';
      var msg =
        mode === 'image'
          ? 'A new container version is now running (' +
            ver +
            (commit ? ', ' + commit : '') +
            '). Reload if the UI looks stale.'
          : 'Webable updated successfully to version ' + ver + (commit ? ' (' + commit + ')' : '') + '.';
      show(msg);
    } else {
      hide();
    }
  }

  function poll() {
    fetch('/api/build-info', { credentials: 'same-origin' })
      .then(function (r) {
        return r.json();
      })
      .then(apply)
      .catch(function () { /* offline */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });
})();
