/**
 * Save a fetch() Response as a file using the server's Content-Disposition filename,
 * so client-side downloads follow the same naming convention as direct links.
 */
(function (global) {
  function filenameFromResponse(res, fallback) {
    var cd = (res && res.headers && res.headers.get('Content-Disposition')) || '';
    var star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    if (star) {
      try { return decodeURIComponent(star[1].trim()); } catch (e) { /* fall through */ }
    }
    var plain = /filename="?([^";]+)"?/i.exec(cd);
    if (plain) return plain[1].trim();
    return fallback || 'Webable_Export';
  }

  async function save(res, fallback) {
    var name = filenameFromResponse(res, fallback);
    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    return name;
  }

  global.WebableDownload = { save: save, filenameFromResponse: filenameFromResponse };
})(typeof window !== 'undefined' ? window : globalThis);
