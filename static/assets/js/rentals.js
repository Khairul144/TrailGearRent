/* ============================================================
   TrailGear Rent — interaksi Modul Keranjang & Pemesanan Sewa
   ============================================================ */
(function () {
  "use strict";

  var HARI = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
  var BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

  /* ---------- Kontrol jadwal terpusat di halaman keranjang ---------- */
  var scheduleForm = document.getElementById("cartScheduleForm");
  if (scheduleForm) {
    var cartStart = document.getElementById("cartStart");
    var cartDuration = document.getElementById("cartDuration");
    var cartReturn = document.getElementById("cartReturn");

    var updateReturnPreview = function () {
      if (!cartStart || !cartStart.value || !cartReturn) return;
      var parts = cartStart.value.split("-").map(Number);
      if (parts.length !== 3) return;
      var days = Math.max(1, parseInt(cartDuration ? cartDuration.value : "1", 10) || 1);
      var retDate = new Date(parts[0], parts[1] - 1, parts[2]);
      retDate.setDate(retDate.getDate() + days + 1);
      cartReturn.textContent =
        HARI[retDate.getDay()] +
        ", " +
        String(retDate.getDate()).padStart(2, "0") +
        " " +
        BULAN[retDate.getMonth()] +
        " " +
        retDate.getFullYear();
    };

    var syncSchedule = function () {
      updateReturnPreview();
      var syncBtn = document.getElementById("btnSyncSchedule");
      if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.textContent = "Menyinkronkan...";
      }
      if (typeof scheduleForm.requestSubmit === "function") {
        scheduleForm.requestSubmit();
      } else {
        scheduleForm.submit();
      }
    };

    if (cartStart) cartStart.addEventListener("change", syncSchedule);
    if (cartDuration) cartDuration.addEventListener("change", syncSchedule);
    updateReturnPreview();
  }

  /* ---------- Kontrol jumlah item keranjang ---------- */
  document.querySelectorAll("form.rt-qty").forEach(function (form) {
    var input = form.querySelector("input[name='quantity']");
    if (!input) return;

    var submitSoon = function () {
      if (form.dataset.dirty === "1") form.requestSubmit();
    };

    form.querySelectorAll("[data-qty-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var step = parseInt(btn.dataset.qtyStep, 10) || 0;
        var min = parseInt(input.min, 10) || 1;
        var max = parseInt(input.max, 10) || 999;
        var next = (parseInt(input.value, 10) || min) + step;
        next = Math.min(Math.max(next, min), max);
        if (next !== parseInt(input.value, 10)) {
          input.value = next;
          form.dataset.dirty = "1";
          submitSoon();
        }
      });
    });

    input.addEventListener("change", function () {
      form.dataset.dirty = "1";
      form.requestSubmit();
    });
  });

  /* ---------- Checkout: tanggal kembali minimal H+1 & filter angka NIK 16 digit ---------- */
  var pickup = document.getElementById("id_pickup_plan_date");
  var ret = document.getElementById("id_return_plan_date");
  if (pickup && ret) {
    var syncReturnMin = function () {
      if (!pickup.value) return;
      var d = new Date(pickup.value + "T00:00:00");
      d.setDate(d.getDate() + 1);
      var iso = d.toISOString().slice(0, 10);
      ret.min = iso;
      if (ret.value && ret.value < iso) ret.value = iso;
    };
    pickup.addEventListener("change", syncReturnMin);
    syncReturnMin();
  }

  var nikInput = document.getElementById("id_id_card_number");
  if (nikInput) {
    nikInput.addEventListener("input", function () {
      var cleaned = nikInput.value.replace(/\D+/g, "").slice(0, 16);
      if (nikInput.value !== cleaned) {
        nikInput.value = cleaned;
      }
    });
  }

  /* ---------- Badge keranjang (dipakai add-to-cart AJAX) ---------- */
  window.trailgearSetCartCount = function (count) {
    var badge = document.querySelector(".cart-badge");
    if (!badge) return;
    badge.textContent = count;
    badge.style.display = count > 0 ? "flex" : "none";
  };
})();
