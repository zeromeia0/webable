/**
 * Emergency fund / invested balances card (partials/balances_card.html).
 * Saves to /instances/{id}/api/balances and broadcasts `webable:balances` with the fresh
 * net worth summary so other widgets on the page can update without a reload.
 */
(function (global) {
  if (global.WebableBalances) return;

  function fmt(n) {
    if (global.WebableCurrency && global.WebableCurrency.format) return global.WebableCurrency.format(Number(n) || 0);
    return Number(n || 0).toFixed(2);
  }

  function parseAmount(raw) {
    var s = String(raw == null ? '' : raw).trim().replace(/\s| /g, '');
    if (!s) return null;
    if (s.indexOf(',') >= 0 && s.indexOf('.') >= 0) {
      s = s.lastIndexOf('.') > s.lastIndexOf(',') ? s.replace(/,/g, '') : s.replace(/\./g, '').replace(',', '.');
    } else {
      s = s.replace(',', '.');
    }
    var v = Number(s);
    return Number.isFinite(v) && v >= 0 ? v : NaN;
  }

  function setOut(card, key, text, eur) {
    card.querySelectorAll('[data-bal-out="' + key + '"]').forEach(function (el) {
      if (eur != null) el.setAttribute('data-eur', String(eur));
      el.textContent = text;
    });
  }

  function render(card, summary) {
    if (!summary) return;
    var t = summary.totals || {};
    var em = summary.emergency || {};
    setOut(card, 'net_worth', fmt(t.net_worth), t.net_worth);
    var nw = card.querySelector('[data-bal-out="net_worth"]');
    if (nw) nw.className = 'mt-1 text-lg font-semibold tabular-nums ' + ((t.net_worth || 0) < 0 ? 'text-rose-300' : 'text-emerald-300');
    setOut(card, 'months_covered', em.months_covered == null ? '—' : (em.months_covered + ' mo'));
    var mc = card.querySelector('[data-bal-out="months_covered"]');
    if (mc) {
      mc.title = em.months_covered == null ? 'Add recurring expenses to measure how many months your emergency fund covers.' : '';
      var colour = { healthy: 'text-emerald-300', building: 'text-amber-300', low: 'text-rose-300' }[em.level] || 'text-slate-300';
      mc.className = 'mt-1 text-lg font-semibold tabular-nums ' + colour;
    }
    setOut(card, 'target', fmt(em.target), em.target);
    setOut(card, 'still_needed', fmt(em.still_needed), em.still_needed);
    setOut(card, 'progress_label', (em.progress_pct || 0) + '%');
    var bar = card.querySelector('[data-bal-out="progress_bar"]');
    if (bar) bar.style.width = Math.max(0, Math.min(100, em.progress_pct || 0)) + '%';
    var form = card.querySelector('[data-balances-form]');
    if (form && summary.balances) {
      ['emergency_fund', 'invested'].forEach(function (k) {
        var inp = form.elements[k];
        if (inp && document.activeElement !== inp) inp.value = Number(summary.balances[k] || 0).toFixed(2);
      });
    }
  }

  function save(card) {
    var form = card.querySelector('[data-balances-form]');
    var msg = card.querySelector('[data-balances-msg]');
    var id = card.getAttribute('data-instance-id');
    var body = {};
    var bad = false;
    ['emergency_fund', 'invested'].forEach(function (k) {
      var v = parseAmount(form.elements[k].value);
      if (Number.isNaN(v)) bad = true;
      else if (v != null) body[k] = v;
    });
    if (bad) {
      msg.className = 'text-xs mt-2 min-h-[1rem] text-rose-300';
      msg.textContent = 'Enter amounts as positive numbers (e.g. 1500 or 1 500,50).';
      return Promise.resolve(null);
    }
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    msg.className = 'text-xs mt-2 min-h-[1rem] text-slate-400';
    msg.textContent = 'Saving…';
    return fetch('/instances/' + id + '/api/balances', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.detail || ('Save failed (' + r.status + ')'));
        return data;
      });
    }).then(function (summary) {
      msg.className = 'text-xs mt-2 min-h-[1rem] text-emerald-300';
      msg.textContent = 'Saved — net worth and related figures updated.';
      broadcast(id, summary);
      return summary;
    }).catch(function (err) {
      msg.className = 'text-xs mt-2 min-h-[1rem] text-rose-300';
      msg.textContent = err.message || 'Could not save.';
      return null;
    }).finally(function () {
      if (btn) btn.disabled = false;
    });
  }

  function broadcast(instanceId, summary) {
    document.querySelectorAll('[data-balances-card][data-instance-id="' + instanceId + '"]').forEach(function (c) {
      c._summary = summary;
      render(c, summary);
    });
    document.dispatchEvent(new CustomEvent('webable:balances', { detail: { instanceId: Number(instanceId), summary: summary } }));
  }

  function init(root) {
    (root || document).querySelectorAll('[data-balances-card]').forEach(function (card) {
      if (card._wbInit) return;
      card._wbInit = true;
      var raw = card.querySelector('[data-balances-json]');
      try { card._summary = JSON.parse(raw ? raw.textContent : 'null'); } catch (e) { card._summary = null; }
      render(card, card._summary);
      var form = card.querySelector('[data-balances-form]');
      if (form) {
        form.addEventListener('submit', function (e) {
          e.preventDefault();
          save(card);
        });
      }
    });
  }

  document.addEventListener('webable:currency', function () {
    document.querySelectorAll('[data-balances-card]').forEach(function (c) { render(c, c._summary); });
  });

  global.WebableBalances = { init: init, broadcast: broadcast, parseAmount: parseAmount, fmt: fmt };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
})(window);
