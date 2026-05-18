/**
 * Safe-to-spend: preset + custom %, localStorage, live amount update.
 */
(function () {
  var STORAGE_KEY = 'webable_safe_to_spend_pct';
  var DEFAULT_PCT = 25;
  var PRESETS = [10, 25, 50, 75, 100];

  function clampPct(n) {
    var x = parseFloat(n);
    if (isNaN(x)) return DEFAULT_PCT;
    return Math.max(0, Math.min(100, x));
  }

  function readPct() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw === null || raw === '') return DEFAULT_PCT;
      return clampPct(raw);
    } catch (e) {
      return DEFAULT_PCT;
    }
  }

  function writePct(pct) {
    try {
      localStorage.setItem(STORAGE_KEY, String(clampPct(pct)));
    } catch (e) { /* ignore */ }
  }

  function safeAmount(savings, pct) {
    var base = Math.max(parseFloat(savings) || 0, 0);
    return Math.round(base * (clampPct(pct) / 100) * 100) / 100;
  }

  function hint(savings, pct) {
    var s = Math.max(parseFloat(savings) || 0, 0);
    var p = clampPct(pct);
    if (s <= 0) return 'Savings are low this month, so safe-to-spend is limited.';
    if (p <= 25) return 'Conservative mode: most of your savings stay protected.';
    if (p >= 75) return 'Flexible mode: a larger share of this month\'s savings is available.';
    return 'Balanced mode: part of this month\'s savings is available to spend.';
  }

  function isPreset(pct) {
    return PRESETS.indexOf(Math.round(pct)) >= 0 && Math.abs(pct - Math.round(pct)) < 0.001;
  }

  function render() {
    var card = document.getElementById('wbSafeToSpendCard');
    var valEl = document.getElementById('wbSafeToSpendValue');
    var sub = document.getElementById('wbSafeToSpendSub');
    var hintEl = document.getElementById('wbSafeToSpendHint');
    var customInput = document.getElementById('wbSafeToSpendCustom');
    if (!card || !valEl) return;

    var savings = parseFloat(card.getAttribute('data-month-savings') || '0') || 0;
    var pct = readPct();
    var amt = safeAmount(savings, pct);

    valEl.setAttribute('data-eur', String(amt));
    valEl.textContent = amt.toFixed(2);
    if (window.WebableCurrency && typeof window.WebableCurrency.apply === 'function') {
      window.WebableCurrency.apply(card);
    }

    if (sub) sub.textContent = 'Based on ' + pct + '% of your current month savings.';
    if (hintEl) hintEl.textContent = hint(savings, pct);

    document.querySelectorAll('[data-safe-pct]').forEach(function (btn) {
      var bPct = parseFloat(btn.getAttribute('data-safe-pct'));
      var active = Math.abs(bPct - pct) < 0.001;
      btn.classList.toggle('wb-safe-pct-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    if (customInput) {
      if (isPreset(pct)) {
        customInput.value = '';
        customInput.placeholder = 'Custom %';
      } else {
        customInput.value = String(pct);
      }
    }
  }

  function setPct(pct) {
    writePct(pct);
    render();
  }

  function init() {
    var card = document.getElementById('wbSafeToSpendCard');
    if (!card) return;

    document.querySelectorAll('[data-safe-pct]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setPct(parseFloat(btn.getAttribute('data-safe-pct')));
      });
    });

    var customInput = document.getElementById('wbSafeToSpendCustom');
    if (customInput) {
      customInput.addEventListener('change', function () {
        if (customInput.value === '' || customInput.value === null) return;
        setPct(customInput.value);
      });
      customInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (customInput.value !== '') setPct(customInput.value);
        }
      });
    }

    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
