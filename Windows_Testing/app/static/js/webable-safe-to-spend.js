/**
 * Safe-to-spend: compact dropdown + optional custom %, localStorage, live update.
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

  function isPreset(pct) {
    return PRESETS.indexOf(Math.round(pct)) >= 0 && Math.abs(pct - Math.round(pct)) < 0.001;
  }

  function render() {
    var card = document.getElementById('wbSafeToSpendCard');
    var valEl = document.getElementById('wbSafeToSpendValue');
    var select = document.getElementById('wbSafeToSpendSelect');
    var customInput = document.getElementById('wbSafeToSpendCustom');
    if (!card || !valEl) return;

    var savings = parseFloat(card.getAttribute('data-month-savings') || '0') || 0;
    var pct = readPct();
    var amt = safeAmount(savings, pct);

    valEl.setAttribute('data-eur', String(amt));
    if (window.WebableCurrency && typeof window.WebableCurrency.format === 'function') {
      valEl.textContent = window.WebableCurrency.format(amt);
    } else {
      valEl.textContent = '€ ' + amt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    if (select) {
      if (isPreset(pct)) {
        select.value = String(Math.round(pct));
        if (customInput) {
          customInput.classList.add('hidden');
          customInput.value = '';
        }
      } else {
        select.value = 'custom';
        if (customInput) {
          customInput.classList.remove('hidden');
          customInput.value = String(pct);
        }
      }
    }
  }

  function setPct(pct) {
    writePct(pct);
    render();
  }

  function init() {
    var card = document.getElementById('wbSafeToSpendCard');
    var select = document.getElementById('wbSafeToSpendSelect');
    var customInput = document.getElementById('wbSafeToSpendCustom');
    if (!card) return;

    if (select) {
      select.addEventListener('change', function () {
        if (select.value === 'custom') {
          if (customInput) {
            customInput.classList.remove('hidden');
            customInput.focus();
            if (customInput.value !== '') setPct(customInput.value);
          }
        } else {
          setPct(select.value);
        }
      });
    }

    if (customInput) {
      customInput.addEventListener('input', function () {
        if (customInput.value === '' || customInput.value === null) return;
        if (window.WebableNumeric && !window.WebableNumeric.isValidDecimalString(customInput.value, { min: 0, max: 100 })) {
          return;
        }
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
    document.addEventListener('webable:currency', render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
