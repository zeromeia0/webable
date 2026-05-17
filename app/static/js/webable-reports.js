/**
 * Reports page: time-range loading, Chart.js updates, PDF export params.
 */
(function (global) {
  function activePointRadii(activeElements, ctx, defaultRadius, hoverRadius) {
    if (!activeElements || !activeElements.length) return defaultRadius;
    for (var i = 0; i < activeElements.length; i++) {
      var el = activeElements[i];
      if (el.datasetIndex === ctx.datasetIndex && el.index === ctx.dataIndex) {
        return hoverRadius;
      }
    }
    return defaultRadius;
  }

  function lineDatasetWithHoverPoints(label, data, color) {
    return {
      label: label,
      data: data,
      borderColor: color,
      backgroundColor: color.replace(')', ',0.15)').replace('rgb', 'rgba').replace('#', 'rgba(') || 'rgba(248,113,113,0.15)',
      tension: 0.25,
      fill: true,
      pointRadius: function (ctx) {
        return activePointRadii(ctx.chart.getActiveElements(), ctx, 3, 8);
      },
      pointHoverRadius: 8,
      pointBackgroundColor: color,
      pointBorderColor: '#0f172a',
      pointBorderWidth: 2,
      pointHitRadius: 12
    };
  }

  // Fix rgba for hex colors
  function lineSpendDataset(label, data) {
    return {
      label: label,
      data: data,
      borderColor: '#f87171',
      backgroundColor: 'rgba(248,113,113,0.15)',
      tension: 0.25,
      fill: true,
      pointRadius: function (ctx) {
        return activePointRadii(ctx.chart.getActiveElements(), ctx, 3, 8);
      },
      pointHoverRadius: 8,
      pointBackgroundColor: '#f87171',
      pointBorderColor: '#f1f5f9',
      pointBorderWidth: 2,
      pointHitRadius: 14
    };
  }

  global.WebableReports = {
    activePointRadii: activePointRadii,
    lineSpendDataset: lineSpendDataset
  };
})(typeof window !== 'undefined' ? window : globalThis);
