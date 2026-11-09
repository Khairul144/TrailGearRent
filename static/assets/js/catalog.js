/* ============================================================
   TrailGear Rent — Interaksi Halaman Katalog & Detail Produk
   Murni Vanilla JavaScript (Tanpa Third-Party)
   ============================================================ */

(function () {
  // 1. Auto-submit untuk checkbox filter kategori/ketersediaan & dropdown urutkan
  document.querySelectorAll(".auto-submit").forEach((el) => {
    el.addEventListener("change", () => {
      if (el.form) {
        el.form.submit();
      }
    });
  });

  // 2. Toggle sidebar filter di layar mobile
  const btnFilterMobile = document.getElementById("btnFilterMobile");
  const catalogSidebar = document.getElementById("catalogSidebar");
  if (btnFilterMobile && catalogSidebar) {
    btnFilterMobile.addEventListener("click", () => {
      catalogSidebar.classList.toggle("open");
    });
  }

  // 3. Kalkulator estimasi biaya & tanggal kembali di halaman detail produk
  const rentForm = document.getElementById("rentForm");
  if (rentForm) {
    const pricePerDay = parseInt(rentForm.dataset.price || "0", 10);
    const rentStart = document.getElementById("rentStart");
    const rentDuration = document.getElementById("rentDuration");
    const rentQty = document.getElementById("rentQty");
    const rentTotal = document.getElementById("rentTotal");
    const rentReturn = document.getElementById("rentReturn");
    const btnAddCart = document.getElementById("btnAddCart");
    const rentNote = document.getElementById("rentNote");

    const HARI = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
    const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

    function formatRupiah(num) {
      return "Rp " + num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    function updateEstimate() {
      const days = Math.max(1, parseInt(rentDuration ? rentDuration.value : "2", 10) || 2);
      const qty = Math.max(1, parseInt(rentQty ? rentQty.value : "1", 10) || 1);
      const total = pricePerDay * days * qty;
      if (rentTotal) {
        rentTotal.textContent = formatRupiah(total);
      }

      if (rentStart && rentStart.value && rentReturn) {
        const parts = rentStart.value.split("-").map(Number);
        if (parts.length === 3) {
          const retDate = new Date(parts[0], parts[1] - 1, parts[2]);
          retDate.setDate(retDate.getDate() + days + 1);
          const formatted = `${HARI[retDate.getDay()]}, ${String(retDate.getDate()).padStart(2, "0")} ${BULAN[retDate.getMonth()]} ${retDate.getFullYear()}`;
          rentReturn.innerHTML = `Maks. pengembalian: <strong>${formatted}</strong>`;
        }
      }
    }

    if (rentStart) {
      const todayIso = new Date().toISOString().split("T")[0];
      rentStart.min = todayIso;
      if (!rentStart.value) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        rentStart.value = tomorrow.toISOString().split("T")[0];
      }
      rentStart.addEventListener("change", updateEstimate);
    }
    if (rentDuration) rentDuration.addEventListener("change", updateEstimate);
    if (rentQty) rentQty.addEventListener("input", updateEstimate);

    updateEstimate();

    if (rentForm && rentNote) {
      rentForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!btnAddCart || btnAddCart.disabled) return;

        const originalLabel = btnAddCart.innerHTML;
        btnAddCart.disabled = true;
        rentNote.hidden = true;

        try {
          const response = await fetch(rentForm.action, {
            method: "POST",
            body: new FormData(rentForm),
            headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
            credentials: "same-origin",
          });
          const data = await response.json();

          rentNote.hidden = false;
          rentNote.textContent = data.message || "Gagal menambahkan ke keranjang.";
          rentNote.classList.toggle("ok", Boolean(data.ok));
          rentNote.classList.toggle("err", !data.ok);

          if (data.ok) {
            if (typeof window.trailgearSetCartCount === "function") {
              window.trailgearSetCartCount(data.cart_items_count);
            } else {
              const badge = document.querySelector(".cart-badge");
              if (badge) {
                badge.textContent = data.cart_items_count;
                badge.style.display = data.cart_items_count > 0 ? "flex" : "none";
              }
            }
            btnAddCart.dataset.added = "1";
            btnAddCart.innerHTML = "Tambah Lagi";
          }
        } catch (error) {
          rentNote.hidden = false;
          rentNote.textContent = "Koneksi bermasalah. Coba lagi sebentar.";
          rentNote.classList.add("err");
        } finally {
          btnAddCart.disabled = false;
          if (!btnAddCart.dataset.added) btnAddCart.innerHTML = originalLabel;
        }
      });
    }
  }
})();
