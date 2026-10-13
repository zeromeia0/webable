/**
 * Display currency. Amounts are stored in the active workspace's base currency
 * (window.WEBABLE_BASE_CURRENCY, set by the top bar). EUR workspaces may optionally be
 * displayed converted (rates from /api/currency/rates); other workspaces always display in
 * their own currency — amounts are never converted or mixed across workspace currencies.
 */
(function (global) {
  var STORAGE_KEY = 'webable_display_currency';
  var SYMBOLS = { EUR: '€', USD: '$', GBP: '£', BRL: 'R$' };

  function baseCode() {
    var b = String(global.WEBABLE_BASE_CURRENCY || 'EUR').toUpperCase();
    return SYMBOLS[b] ? b : 'EUR';
  }
  var ratesFromEur = { USD: 0, GBP: 0, BRL: 0 };
  var updatedAt = null;
  var usingFallback = false;
  var fetchError = null;

  function getCode() {
    if (baseCode() !== 'EUR') return baseCode();
    var c = 'EUR';
    try { c = (localStorage.getItem(STORAGE_KEY) || 'EUR').toUpperCase(); } catch (e) { c = 'EUR'; }
    if (c !== 'EUR' && c !== 'USD' && c !== 'GBP' && c !== 'BRL') return 'EUR';
    return c;
  }

  function setCode(code) {
    if (baseCode() !== 'EUR') return;
    try { localStorage.setItem(STORAGE_KEY, (code || 'EUR').toUpperCase()); } catch (e) { /* ignore */ }
    document.dispatchEvent(new CustomEvent('webable:currency'));
  }

  function convertFromEur(eur, code) {
    var c = code || getCode();
    if (c === baseCode()) return Number(eur);
    if (c === 'EUR') return Number(eur);
    var r = ratesFromEur[c];
    if (!r || r <= 0) return Number(eur);
    return Math.round(Number(eur) * r * 100) / 100;
  }

  function format(eur) {
    var c = getCode();
    var n = convertFromEur(eur, c);
    var sym = SYMBOLS[c] || c;
    return sym + ' ' + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function scanMoney(root) {
    var scope = root || document;
    scope.querySelectorAll('[data-eur]').forEach(function (el) {
      var raw = el.getAttribute('data-eur');
      if (raw == null || raw === '') return;
      var v = parseFloat(raw);
      if (Number.isNaN(v)) return;
      el.textContent = format(v);
    });
  }

  function updateFxStatus() {
    var fx = document.getElementById('fxStatus');
    var fu = document.getElementById('fxUpdated');
    if (fu && updatedAt) {
      fu.textContent = 'FX: ' + updatedAt.replace('T', ' ').slice(0, 19) + ' UTC';
      fu.classList.remove('hidden');
    }
    if (fx) {
      if (fetchError || usingFallback) {
        fx.textContent = fetchError ? 'FX: using last cached rates.' : 'FX: rates may be stale.';
        fx.classList.remove('hidden');
      } else {
        fx.classList.add('hidden');
      }
    }
  }

  function refreshRates() {
    return fetch('/api/currency/rates', { credentials: 'same-origin' })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        ratesFromEur.USD = Number(d.rates && d.rates.USD) || 0;
        ratesFromEur.GBP = Number(d.rates && d.rates.GBP) || 0;
        ratesFromEur.BRL = Number(d.rates && d.rates.BRL) || 0;
        updatedAt = d.updated_at || null;
        usingFallback = !!d.using_fallback;
        fetchError = d.fetch_error || null;
        updateFxStatus();
      })
      .catch(function () {
        fetchError = 'offline';
        updateFxStatus();
      });
  }

  function initCurrencySelect() {
    var sel = document.getElementById('wbCurrencySelect');
    if (!sel) return;
    if (baseCode() !== 'EUR') {
      sel.value = baseCode();
      sel.disabled = true;
      sel.title = 'This workspace uses ' + baseCode() + '. Amounts are shown in the workspace currency.';
      return;
    }
    sel.value = getCode();
    sel.addEventListener('change', function () {
      setCode(sel.value);
    });
  }

  function init() {
    initCurrencySelect();
    refreshRates().then(function () {
      scanMoney(document);
      if (global.WebableCharts) {
        global.WebableCharts.fmtEUR = function (n) {
          return format(Number(n));
        };
      }
    });
    document.addEventListener('webable:currency', function () {
      var s = document.getElementById('wbCurrencySelect');
      if (s) s.value = getCode();
      scanMoney(document);
      if (typeof window.webableRefreshCharts === 'function') window.webableRefreshCharts();
    });
    setInterval(function () {
      refreshRates().then(function () {
        scanMoney(document);
        if (typeof window.webableRefreshCharts === 'function') window.webableRefreshCharts();
      });
    }, 8 * 3600 * 1000);
  }

  global.WebableCurrency = {
    getCode: getCode,
    baseCode: baseCode,
    setCode: setCode,
    format: format,
    convertFromEur: convertFromEur,
    scanMoney: scanMoney,
    refreshRates: refreshRates,
    init: init,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(typeof window !== 'undefined' ? window : globalThis);
