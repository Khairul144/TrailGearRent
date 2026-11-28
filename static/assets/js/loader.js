/* ============================================================
   TrailGear Rent — Compass Loader Controller
   1) Top progress bar pada setiap perpindahan halaman internal
   2) Full-page compass overlay pada submit form penting / navigasi lambat
   3) Mini-spinner kompas otomatis pada tombol submit form POST
   ============================================================ */
(function () {
  if (window.__tgLoaderInitialized) return;
  window.__tgLoaderInitialized = true;

  const overlay = document.getElementById("tgLoaderOverlay");
  const overlayText = document.getElementById("tgLoaderText");
  const pageBar = document.getElementById("tgPageBar");
  const DEFAULT_TEXT = "Memuat TrailGear...";

  let overlayTimer = null;
  let failsafeTimer = null;
  const activeButtons = [];

  function showBar() {
    if (!pageBar) return;
    pageBar.hidden = false;
    requestAnimationFrame(() => pageBar.classList.add("is-active"));
  }

  function showOverlay(text, delayMs) {
    if (!overlay) return;
    if (overlayText) overlayText.textContent = text || DEFAULT_TEXT;
    clearTimeout(overlayTimer);
    clearTimeout(failsafeTimer);

    const reveal = () => {
      overlay.hidden = false;
      requestAnimationFrame(() => overlay.classList.add("is-active"));
    };

    if (delayMs && delayMs > 0) {
      overlayTimer = setTimeout(reveal, delayMs);
    } else {
      reveal();
    }

    // Failsafe agar overlay tidak pernah macet bila navigasi dibatalkan/download
    failsafeTimer = setTimeout(hideAll, 12000);
  }

  function restoreButtons() {
    while (activeButtons.length) {
      const rec = activeButtons.pop();
      if (!rec.btn) continue;
      rec.btn.classList.remove("tg-btn-loading");
      rec.btn.disabled = false;
      rec.btn.removeAttribute("aria-busy");
      if (rec.html !== null) rec.btn.innerHTML = rec.html;
    }
  }

  function hideAll() {
    clearTimeout(overlayTimer);
    clearTimeout(failsafeTimer);
    if (pageBar) {
      pageBar.classList.remove("is-active");
      setTimeout(() => {
        if (!pageBar.classList.contains("is-active")) pageBar.hidden = true;
      }, 200);
    }
    if (overlay) {
      overlay.classList.remove("is-active");
      setTimeout(() => {
        if (!overlay.classList.contains("is-active")) overlay.hidden = true;
      }, 240);
    }
    restoreButtons();
  }

  function makeMiniCompassSvg() {
    return (
      '<svg class="tg-mini-compass" viewBox="0 0 16 16" aria-hidden="true">' +
      '<polygon points="8,1.5 10.5,8 8,14.5 5.5,8" fill="currentColor"/>' +
      "</svg>"
    );
  }

  function setButtonLoading(btn, label) {
    if (!btn || btn.classList.contains("tg-btn-loading")) return;
    const origHtml = btn.innerHTML;
    activeButtons.push({ btn, html: origHtml });
    btn.classList.add("tg-btn-loading");
    btn.setAttribute("aria-busy", "true");
    // Jangan disable sebelum submit selesai di event loop yang sama agar form tetap terkirim
    const cleanText = label !== undefined ? label : (btn.textContent || "").trim();
    const inner = document.createElement("span");
    inner.className = "tg-btn-loading-inner";
    inner.innerHTML = makeMiniCompassSvg();
    if (cleanText) {
      const textSpan = document.createElement("span");
      textSpan.textContent = cleanText;
      inner.appendChild(textSpan);
    }
    btn.innerHTML = "";
    btn.appendChild(inner);
    setTimeout(() => {
      if (btn.classList.contains("tg-btn-loading")) btn.disabled = true;
    }, 0);
  }

  // Expose API kecil jika ada script lain (mis. fetch) yang ingin memicu loader
  window.TrailGearLoader = {
    show: (text) => {
      showBar();
      showOverlay(text || DEFAULT_TEXT, 0);
    },
    bar: showBar,
    hide: hideAll,
    button: setButtonLoading,
  };

  function isDownloadOrExternalLink(a) {
    const href = a.getAttribute("href") || "";
    if (!href || href === "#" || href.startsWith("#")) return true;
    if (/^(javascript:|mailto:|tel:|blob:|data:)/i.test(href)) return true;
    if (a.hasAttribute("download")) return true;
    if (a.target && a.target !== "_self") return true;
    if (a.dataset.noLoader !== undefined) return true;
    // Jangan tampilkan overlay/bar permanen untuk unduhan CSV atau bukti file
    if (/[?&]export=csv\b/i.test(href) || /\/proof\/?$/i.test(href)) return true;
    try {
      const targetUrl = new URL(a.href, window.location.href);
      if (targetUrl.origin !== window.location.origin) return true;
      // Hanya anchor di halaman yang sama
      if (
        targetUrl.pathname === window.location.pathname &&
        targetUrl.search === window.location.search &&
        targetUrl.hash
      ) {
        return true;
      }
    } catch (_) {
      return true;
    }
    return false;
  }

  // 1. Klik tautan internal -> top progress bar langsung + kompas overlay bila > 220ms
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented) return;
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest("a[href]");
    if (!a || isDownloadOrExternalLink(a)) return;
    showBar();
    showOverlay(a.dataset.loaderText || DEFAULT_TEXT, 220);
  });

  // 2. Submit form -> top bar + mini compass spinner pada tombol + overlay untuk POST/upload
  document.addEventListener("submit", (e) => {
    // Biarkan listener validasi form lain berjalan lebih dulu via setTimeout(0)
    const form = e.target;
    if (!form || form.dataset.noLoader !== undefined) return;
    if (form.id === "scanLookupForm") return; // Modal AJAX sudah punya indikator sendiri
    const submitter = e.submitter || form.querySelector('button[type="submit"], input[type="submit"]');

    setTimeout(() => {
      if (e.defaultPrevented) return;
      const method = (form.getAttribute("method") || "get").toLowerCase();
      const action = form.getAttribute("action") || "";
      if (/[?&]export=csv\b/i.test(action)) return;

      showBar();
      if (method === "post") {
        // Pertahankan name/value tombol submitter jika tombol di-disable
        if (submitter && submitter.name && !form.querySelector(`input[type="hidden"][name="${CSS.escape(submitter.name)}"]`)) {
          const hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = submitter.name;
          hidden.value = submitter.value || "";
          form.appendChild(hidden);
        }
        if (submitter && submitter.tagName === "BUTTON") {
          const origText = (submitter.textContent || "").trim();
          const customLabel = submitter.dataset.loadingText || (origText ? "Memproses..." : "");
          setButtonLoading(submitter, customLabel);
        }
        const isUpload = (form.getAttribute("enctype") || "").includes("multipart");
        const msg =
          form.dataset.loaderText ||
          (isUpload ? "Mengunggah berkas & memproses..." : "Memproses permintaan...");
        showOverlay(msg, isUpload ? 0 : 180);
      } else {
        showOverlay("Memuat hasil...", 260);
      }
    }, 0);
  });

  // Bersihkan state saat halaman tampil lagi (termasuk Back/Forward bfcache)
  window.addEventListener("pageshow", hideAll);
  window.addEventListener("load", hideAll);
})();
