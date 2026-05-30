/**
 * Shared Chart.js defaults for Webable (dark theme, readable tooltips).
 */
(function (global) {
  function fmtEUR(n) {
    if (n == null || Number.isNaN(Number(n))) return '—';
    return (
      'EUR ' +
      Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function fmtPct(n, digits) {
    const d = digits == null ? 1 : digits;
    if (n == null || Number.isNaN(Number(n))) return '—';
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: d }) + '%';
  }

  function darkChartOptions(extra) {
    return Object.assign(
      {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#cbd5e1', boxWidth: 12, padding: 10 } },
          tooltip: {
            backgroundColor: 'rgba(15, 23, 42, 0.97)',
            titleColor: '#f8fafc',
            bodyColor: '#e2e8f0',
            borderColor: '#475569',
            borderWidth: 1,
            padding: 12,
            bodySpacing: 6,
            titleSpacing: 8,
            titleFont: { size: 13, weight: '600' },
            bodyFont: { size: 12 },
            displayColors: true,
            boxPadding: 5,
            usePointStyle: true,
            caretPadding: 12,
            cornerRadius: 8
          }
        },
        scales: {
          x: { ticks: { color: '#94a3b8', maxTicksLimit: 24 } },
          y: { ticks: { color: '#94a3b8' } }
        }
      },
      extra || {}
    );
  }

  global.WebableCharts = {
    fmtEUR,
    fmtPct,
    darkChartOptions
  };
})(typeof window !== 'undefined' ? window : globalThis);
