/**
 * Global quick calculator (vanilla JS). Mirrors app.services.calculator_eval semantics.
 */
(function (global) {
  'use strict';

  var ALLOWED = /^[\d+\-*/().\s]+$/;

  function tokenize(expr) {
    var tokens = [];
    var i = 0;
    while (i < expr.length) {
      var c = expr[i];
      if (/\s/.test(c)) {
        i++;
        continue;
      }
      if ('+-*/()'.indexOf(c) >= 0) {
        tokens.push(c);
        i++;
        continue;
      }
      if (/[\d.]/.test(c)) {
        var j = i;
        while (j < expr.length && /[\d.]/.test(expr[j])) j++;
        tokens.push(expr.slice(i, j));
        i = j;
        continue;
      }
      throw new Error('invalid');
    }
    return tokens;
  }

  function parseTokens(tokens) {
    var pos = 0;
    function peek() {
      return pos < tokens.length ? tokens[pos] : null;
    }
    function consume(expected) {
      var t = peek();
      if (t === null) throw new Error('end');
      if (expected != null && t !== expected) throw new Error('expected');
      pos++;
      return t;
    }
    function parseExpr() {
      var left = parseTerm();
      while (peek() === '+' || peek() === '-') {
        var op = consume();
        var right = parseTerm();
        left = op === '+' ? left + right : left - right;
      }
      return left;
    }
    function parseTerm() {
      var left = parseUnary();
      while (peek() === '*' || peek() === '/') {
        var op = consume();
        var right = parseUnary();
        if (op === '/') {
          if (right === 0) throw new Error('div0');
          left = left / right;
        } else {
          left = left * right;
        }
      }
      return left;
    }
    function parseUnary() {
      if (peek() === '-') {
        consume();
        return -parseUnary();
      }
      if (peek() === '+') {
        consume();
        return parseUnary();
      }
      return parsePrimary();
    }
    function parsePrimary() {
      var t = peek();
      if (t === '(') {
        consume('(');
        var v = parseExpr();
        consume(')');
        return v;
      }
      if (t === null || '+-*/))'.indexOf(t) >= 0) throw new Error('empty');
      consume();
      return parseFloat(t);
    }
    var result = parseExpr();
    if (pos !== tokens.length) throw new Error('trail');
    return result;
  }

  function safeEval(expr) {
    var raw = String(expr || '').trim();
    if (!raw) return { ok: false, error: 'empty' };
    if (!ALLOWED.test(raw)) return { ok: false, error: 'invalid characters' };
    try {
      var value = parseTokens(tokenize(raw));
      if (Number.isNaN(value)) return { ok: false, error: 'not a number' };
      return { ok: true, value: value };
    } catch (e) {
      if (e && e.message === 'div0') return { ok: false, error: 'division by zero' };
      return { ok: false, error: 'invalid expression' };
    }
  }

  function formatDisplay(n) {
    var s = String(n);
    if (s.length > 14) return Number(n).toPrecision(10);
    return s;
  }

  function init() {
    var fab = document.getElementById('globalCalcFab');
    var panel = document.getElementById('globalCalcPanel');
    var closeBtn = document.getElementById('globalCalcClose');
    var display = document.getElementById('globalCalcDisplay');
    var errEl = document.getElementById('globalCalcError');
    if (!fab || !panel || !display) return;

    var expr = '';
    var lastOk = null;

    function render() {
      display.textContent = expr || (lastOk != null ? formatDisplay(lastOk) : '0');
      if (errEl) errEl.textContent = '';
    }

    function setError(msg) {
      if (errEl) errEl.textContent = msg || '';
    }

    function append(ch) {
      expr += ch;
      render();
    }

    function clearAll() {
      expr = '';
      lastOk = null;
      render();
    }

    function backspace() {
      if (expr.length) {
        expr = expr.slice(0, -1);
        render();
      }
    }

    function equals() {
      if (!expr.trim()) return;
      var res = safeEval(expr);
      if (!res.ok) {
        setError(res.error === 'division by zero' ? 'Cannot divide by zero' : 'Invalid expression');
        return;
      }
      lastOk = res.value;
      expr = formatDisplay(res.value);
      render();
    }

    fab.addEventListener('click', function () {
      panel.classList.toggle('hidden');
      var open = !panel.classList.contains('hidden');
      fab.setAttribute('aria-expanded', open ? 'true' : 'false');
      var aiPanel = document.getElementById('globalAiPanel');
      if (aiPanel && open) aiPanel.classList.add('hidden');
    });
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        panel.classList.add('hidden');
      });
    }

    panel.querySelectorAll('[data-calc]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.getAttribute('data-calc');
        if (action === 'C') return clearAll();
        if (action === '⌫') return backspace();
        if (action === '=') return equals();
        append(action);
      });
    });

    document.addEventListener('keydown', function (e) {
      if (panel.classList.contains('hidden')) return;
      if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
      if (e.key >= '0' && e.key <= '9') {
        e.preventDefault();
        append(e.key);
      } else if (e.key === '.') {
        e.preventDefault();
        append('.');
      } else if ('+-*/()'.indexOf(e.key) >= 0) {
        e.preventDefault();
        append(e.key);
      } else if (e.key === 'Enter' || e.key === '=') {
        e.preventDefault();
        equals();
      } else if (e.key === 'Escape') {
        panel.classList.add('hidden');
      } else if (e.key === 'Backspace') {
        e.preventDefault();
        backspace();
      } else if (e.key === 'Delete' || e.key.toLowerCase() === 'c') {
        e.preventDefault();
        clearAll();
      }
    });

    render();
  }

  global.WebableCalculator = { safeEval: safeEval, init: init };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(typeof window !== 'undefined' ? window : globalThis);
