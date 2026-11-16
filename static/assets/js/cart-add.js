/* ============================================================
   TrailGear Rent — Floating Toast Notification & Quick Add-to-Cart
   Dimuat di semua halaman lewat partials/scripts.html.
   Tanpa JavaScript, form tetap POST biasa dan redirect kembali.
   ============================================================ */
(function () {
  "use strict";

  var MAX_TOASTS = 4;
  var DEFAULT_DURATION = 3800;

  function ensureToastContainer() {
    var container = document.getElementById("tgToastContainer");
    if (!container) {
      container = document.createElement("div");
      container.id = "tgToastContainer";
      container.className = "tg-toast-container";
      container.setAttribute("aria-live", "polite");
      container.setAttribute("aria-atomic", "false");
      document.body.appendChild(container);
    }
    return container;
  }

  function createIconSvg(type) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2.5");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");

    var path = document.createElementNS(ns, "path");
    if (type === "error") {
      path.setAttribute("d", "M18 6L6 18M6 6l12 12");
    } else {
      path.setAttribute("d", "M20 6L9 17l-5-5");
    }
    svg.appendChild(path);
    return svg;
  }

  function safeRelativeUrl(candidate, fallback) {
    if (typeof candidate === "string" && /^\/(?!\/)/.test(candidate)) {
      return candidate;
    }
    return fallback;
  }

  function showToast(message, options) {
    options = options || {};
    var type = options.type === "error" ? "error" : "success";
    var duration = typeof options.duration === "number" ? options.duration : DEFAULT_DURATION;
    var container = ensureToastContainer();

    while (container.children.length >= MAX_TOASTS) {
      container.removeChild(container.firstElementChild);
    }

    var toast = document.createElement("div");
    toast.className = "tg-toast tg-toast--" + type;
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    var iconWrap = document.createElement("span");
    iconWrap.className = "tg-toast-icon";
    iconWrap.appendChild(createIconSvg(type));

    var body = document.createElement("div");
    body.className = "tg-toast-body";

    var title = document.createElement("div");
    title.className = "tg-toast-title";
    title.textContent =
      options.title || (type === "error" ? "Gagal Menambahkan" : "Masuk Keranjang");

    var msg = document.createElement("div");
    msg.className = "tg-toast-msg";
    msg.textContent = String(message || "");

    body.appendChild(title);
    body.appendChild(msg);

    if (type === "success" && options.showCartLink !== false) {
      var link = document.createElement("a");
      link.className = "tg-toast-link";
      link.href = safeRelativeUrl(options.cartUrl, "/cart/");
      var countSuffix =
        typeof options.cartCount === "number" && options.cartCount > 0
          ? " (" + options.cartCount + " unit)"
          : "";
      link.textContent = "Lihat Keranjang" + countSuffix + " \u2192";
      body.appendChild(link);
    }

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "tg-toast-close";
    closeBtn.setAttribute("aria-label", "Tutup notifikasi");
    closeBtn.textContent = "\u00D7";

    var bar = document.createElement("span");
    bar.className = "tg-toast-bar";
    bar.style.animationDuration = duration + "ms";

    toast.appendChild(iconWrap);
    toast.appendChild(body);
    toast.appendChild(closeBtn);
    toast.appendChild(bar);
    container.appendChild(toast);

    requestAnimationFrame(function () {
      toast.classList.add("is-visible");
    });

    var timerId = null;
    var dismissed = false;

    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      if (timerId) clearTimeout(timerId);
      toast.classList.remove("is-visible");
      toast.classList.add("is-leaving");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 240);
    }

    function startTimer(ms) {
      if (timerId) clearTimeout(timerId);
      timerId = setTimeout(dismiss, ms);
    }

    closeBtn.addEventListener("click", dismiss);
    toast.addEventListener("mouseenter", function () {
      if (timerId) clearTimeout(timerId);
    });
    toast.addEventListener("mouseleave", function () {
      startTimer(1600);
    });

    startTimer(duration);
    return toast;
  }

  function setCartCount(count) {
    var numeric = parseInt(count, 10) || 0;
    document.querySelectorAll(".cart-badge").forEach(function (badge) {
      badge.textContent = numeric;
      badge.style.display = numeric > 0 ? "flex" : "none";
    });
    var detailCartLink = document.querySelector(".detail-cart-link");
    if (detailCartLink) {
      var svg = detailCartLink.querySelector("svg");
      detailCartLink.textContent = " Lihat keranjang (" + numeric + ")";
      if (svg) detailCartLink.insertBefore(svg, detailCartLink.firstChild);
    }
  }

  window.trailgearToast = showToast;
  window.trailgearSetCartCount = setCartCount;

  document.querySelectorAll("form.card-add").forEach(function (form) {
    var button = form.querySelector(".btn-add-cart");
    var label = form.querySelector(".btn-add-cart-label");
    if (!button) return;

    var originalText = label ? label.textContent : button.textContent;

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (button.disabled) return;

      button.disabled = true;
      if (label) label.textContent = "Menambahkan...";

      try {
        var response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
          },
          credentials: "same-origin",
        });
        var data = await response.json();

        if (data.ok) {
          setCartCount(data.cart_items_count);
          showToast(data.message || "Produk ditambahkan ke keranjang.", {
            type: "success",
            cartCount: data.cart_items_count,
            cartUrl: data.cart_url || "/cart/",
            showCartLink: true,
          });
          button.classList.add("is-added");
          if (label) label.textContent = "Ditambahkan \u2713";
          setTimeout(function () {
            button.classList.remove("is-added");
            if (label) label.textContent = originalText;
            button.disabled = false;
          }, 2200);
        } else {
          if (label) label.textContent = originalText;
          button.disabled = false;
          showToast(data.message || "Gagal menambahkan ke keranjang.", {
            type: "error",
          });
        }
      } catch (error) {
        if (label) label.textContent = originalText;
        button.disabled = false;
        showToast("Koneksi bermasalah. Coba lagi sebentar.", {
          type: "error",
        });
      }
    });
  });
})();
