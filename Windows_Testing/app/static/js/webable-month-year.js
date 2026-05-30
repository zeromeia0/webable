/**
 * Month/year pickers: syncs <select class="wb-my-m"> + <select class="wb-my-y"> with hidden input[name].
 * Wrapper: .wb-my-picker with optional data-default="YYYY-MM"
 */
(function () {
  const MONTHS = [
    ['01', 'January'],
    ['02', 'February'],
    ['03', 'March'],
    ['04', 'April'],
    ['05', 'May'],
    ['06', 'June'],
    ['07', 'July'],
    ['08', 'August'],
    ['09', 'September'],
    ['10', 'October'],
    ['11', 'November'],
    ['12', 'December'],
  ];

  function parseYm(s) {
    if (!s || typeof s !== 'string') return null;
    var m = s.trim().match(/^(\d{4})-(\d{2})/);
    if (!m) return null;
    return { y: m[1], mo: m[2] };
  }

  function buildYearSelect(sel, y) {
    var cy = new Date().getFullYear();
    sel.innerHTML = '';
    for (var yr = cy + 6; yr >= cy - 10; yr--) {
      var o = document.createElement('option');
      o.value = String(yr);
      o.textContent = String(yr);
      if (String(yr) === y) o.selected = true;
      sel.appendChild(o);
    }
  }

  function syncHidden(picker) {
    var h = picker.querySelector('.wb-my-hidden');
    var m = picker.querySelector('.wb-my-m');
    var y = picker.querySelector('.wb-my-y');
    if (!h || !m || !y) return;
    h.value = y.value + '-' + m.value;
    h.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function initPicker(picker) {
    var h = picker.querySelector('.wb-my-hidden');
    var mSel = picker.querySelector('.wb-my-m');
    var ySel = picker.querySelector('.wb-my-y');
    if (!h || !mSel || !ySel) return;
    var def = h.getAttribute('value') || picker.getAttribute('data-default') || '';
    var parsed = parseYm(def);
    var y = parsed ? parsed.y : String(new Date().getFullYear());
    var idx = parsed ? parseInt(parsed.mo, 10) : new Date().getMonth() + 1;
    var mo = idx >= 1 && idx <= 12 ? (idx < 10 ? '0' : '') + idx : '01';

    mSel.innerHTML = '';
    MONTHS.forEach(function (pair) {
      var o = document.createElement('option');
      o.value = pair[0];
      o.textContent = pair[1];
      if (pair[0] === mo) o.selected = true;
      mSel.appendChild(o);
    });
    buildYearSelect(ySel, y);
    syncHidden(picker);
    mSel.addEventListener('change', function () {
      syncHidden(picker);
    });
    ySel.addEventListener('change', function () {
      syncHidden(picker);
    });
  }

  function init() {
    document.querySelectorAll('.wb-my-picker').forEach(initPicker);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
