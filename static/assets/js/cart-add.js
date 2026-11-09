/* ============================================================
   TrailGear Rent — tombol "Tambah keranjang" pada kartu produk.
   Dimuat di semua halaman lewat partials/scripts.html.
   Tanpa JavaScript, form tetap POST biasa dan redirect kembali.
   ============================================================ */
(function () {
  "use strict";

  function setCartCount(count) {
    var badge = document.querySelector(".cart-badge");
    if (!badge) return;
    badge.textContent = count;
    badge.style.display = count > 0 ? "flex" : "none";
  }

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
          button.classList.add("is-added");
          if (label) label.textContent = "Ditambahkan ✓";
          setTimeout(function () {
            button.classList.remove("is-added");
            if (label) label.textContent = originalText;
            button.disabled = false;
          }, 2200);
        } else {
          if (label) label.textContent = originalText;
          button.disabled = false;
          window.alert(data.message || "Gagal menambahkan ke keranjang.");
        }
      } catch (error) {
        if (label) label.textContent = originalText;
        button.disabled = false;
        window.alert("Koneksi bermasalah. Coba lagi sebentar.");
      }
    });
  });
})();
