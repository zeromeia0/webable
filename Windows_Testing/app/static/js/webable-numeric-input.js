/**
 * Reject scientific notation, letters, and invalid decimals in numeric fields.
 */
(function (global) {
  'use strict';

  var DECIMAL_RE = /^-?(\d+)(\.\d*)?$/;

  function normalizeRaw(s) {
    return String(s || '')
      .trim()
      .replace(/,/g, '.');
  }

  function isValidDecimalString(s, opts) {
    opts = opts || {};
    var raw = normalizeRaw(s);
    if (!raw || /[eE]/.test(raw)) return false;
    if (!DECIMAL_RE.test(raw)) return false;
    var n = parseFloat(raw);
    if (Number.isNaN(n)) return false;
    if (!opts.allowNegative && n < 0) return false;
    if (opts.min != null && n < opts.min) return false;
    if (opts.max != null && n > opts.max) return false;
    return true;
  }

  function sanitizeWhileTyping(s, opts) {
    opts = opts || {};
    var allowNeg = !!opts.allowNegative;
    var out = '';
    var seenDot = false;
    var i = 0;
    var raw = String(s || '');
    if (allowNeg && raw.charAt(0) === '-') {
      out = '-';
      i = 1;
    }
    for (; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (ch >= '0' && ch <= '9') {
        out += ch;
      } else if ((ch === '.' || ch === ',') && !seenDot) {
        out += '.';
        seenDot = true;
      }
    }
    return out;
  }

  function readOpts(input) {
    var min = input.getAttribute('min');
    var max = input.getAttribute('max');
    return {
      allowNegative: min === null || parseFloat(min) < 0,
      min: min !== null && min !== '' ? parseFloat(min) : null,
      max: max !== null && max !== '' ? parseFloat(max) : null,
    };
  }

  function bindInput(input) {
    if (!input || input.dataset.wbDecimalBound === '1') return;
    input.dataset.wbDecimalBound = '1';

    if (input.type === 'number') {
      input.type = 'text';
      input.setAttribute('inputmode', 'decimal');
      input.setAttribute('autocomplete', 'off');
    }
    input.classList.add('wb-decimal-input');

    function onInput() {
      var opts = readOpts(input);
      var cleaned = sanitizeWhileTyping(input.value, opts);
      if (input.value !== cleaned) input.value = cleaned;
    }

    function onPaste(e) {
      e.preventDefault();
      var pasted = (e.clipboardData || global.clipboardData).getData('text');
      var opts = readOpts(input);
      var cleaned = sanitizeWhileTyping(pasted, opts);
      if (isValidDecimalString(cleaned, opts) || cleaned === '' || cleaned === '-') {
        input.value = cleaned;
      }
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function onBlur() {
      var opts = readOpts(input);
      var raw = normalizeRaw(input.value);
      if (raw === '' || raw === '-') {
        input.value = '';
        return;
      }
      if (!isValidDecimalString(raw, opts)) {
        input.value = '';
        input.setCustomValidity('Enter a valid number (no letters or scientific notation).');
      } else {
        input.setCustomValidity('');
        var n = parseFloat(raw);
        input.value = String(n);
      }
    }

    input.addEventListener('input', onInput);
    input.addEventListener('paste', onPaste);
    input.addEventListener('blur', onBlur);
  }

  function init(root) {
    var scope = root || document;
    scope.querySelectorAll('input[type="number"], input.wb-decimal-input, [data-wb-decimal]').forEach(bindInput);
  }

  global.WebableNumeric = {
    isValidDecimalString: isValidDecimalString,
    sanitizeWhileTyping: sanitizeWhileTyping,
    parse: function (s, opts) {
      if (!isValidDecimalString(s, opts)) return null;
      return parseFloat(normalizeRaw(s));
    },
    init: init,
  };

  document.addEventListener(
    'submit',
    function (e) {
      var form = e.target;
      if (!form || !form.querySelectorAll) return;
      var blocked = false;
      form.querySelectorAll('.wb-decimal-input').forEach(function (input) {
        var opts = readOpts(input);
        if (input.value && !isValidDecimalString(input.value, opts)) {
          input.setCustomValidity('Enter a valid number (no letters or scientific notation).');
          blocked = true;
        }
        if (!input.checkValidity()) blocked = true;
      });
      if (blocked) e.preventDefault();
    },
    true
  );

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      init(document);
    });
  } else {
    init(document);
  }
})(typeof window !== 'undefined' ? window : globalThis);
