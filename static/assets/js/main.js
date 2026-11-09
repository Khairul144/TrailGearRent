/* ============================================================
   Foresta Adventure — Landing Page Clone
   ============================================================ */

// ---------- Data produk ----------
// Produk kini dirender server-side dari database (app "catalog"),
// lihat templates/catalog/_product_card.html.

// ---------- Data testimoni ----------
const TESTIMONIALS = [
  { title: "Kualitas barang bagus", quote: "Harganya affordable banget dan cocok di kantong campers pemula", name: "Lucene" },
  { title: "Proses cepat dan admin ramah", quote: "Prosesnya cepat, adminnya ramah dan bisa ngasih solusi peralatan bagi campers pemula", name: "Kaname" },
  { title: "Selalu jadi langganan", quote: "Tidak pernah kecewa, langganan selalu di sini karena kondisi barangnya bagus dan dikasih bonus 1 hari pengembalian", name: "Aditya Mahendra" },
];

// ---------- Render testimoni (2x seperti loop asli) ----------
const testiSlider = document.getElementById("testiSlider");
if (testiSlider) {
  const star = '<img src="assets/img/icons/star-black.svg" alt="Bintang">';
  const avatar = "assets/img/avatar/avatar.jpg";
  const card = t => `
    <div class="card-testimonial wow">
      <div class="testi-stars">${star.repeat(5)}</div>
      <p class="testi-title">${t.title}</p>
      <p class="testi-quote">${t.quote}</p>
      <div class="testi-author">
        <img src="${avatar}" alt="Avatar ${t.name}">
        <span class="testi-name">${t.name}</span>
      </div>
    </div>`;
  const loop = [...TESTIMONIALS, ...TESTIMONIALS];
  testiSlider.innerHTML = loop.map(card).join("");
}

// ---------- Real-time Interactive Datepicker & Durasi ----------
const HARI = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const BULAN_FULL = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];

function fmt(d) {
  return `${HARI[d.getDay()]}, ${String(d.getDate()).padStart(2, "0")} ${BULAN[d.getMonth()]} ${d.getFullYear()}`;
}

function calcReturnDate(pickupDate, days) {
  const ret = new Date(pickupDate);
  // Sewa N hari: pengambilan hari H, masa sewa N hari, pengembalian H + N + 1
  ret.setDate(ret.getDate() + days + 1);
  return ret;
}

function isSameDate(d1, d2) {
  return d1.getFullYear() === d2.getFullYear() &&
         d1.getMonth() === d2.getMonth() &&
         d1.getDate() === d2.getDate();
}

function isPastDate(d, ref) {
  const dCopy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const refCopy = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
  return dCopy < refCopy;
}

const today = new Date();
let currentPickup = new Date(today);
currentPickup.setDate(today.getDate() + 1); // default: besok
let currentDuration = 2; // default: 2 hari

// Jadwal yang sudah dipilih sebelumnya (dikirim server lewat data-* di #scheduleForm)
const scheduleForm = document.getElementById("scheduleForm");
const tglAmbilValue = document.getElementById("tglAmbilValue");
const durasiValue = document.getElementById("durasiValue");

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

if (scheduleForm) {
  const ds = scheduleForm.dataset.start;
  if (ds && /^\d{4}-\d{2}-\d{2}$/.test(ds)) {
    const [y, m, d] = ds.split("-").map(Number);
    const parsed = new Date(y, m - 1, d);
    if (!isPastDate(parsed, today)) currentPickup = parsed;
  }
  const dd = parseInt(scheduleForm.dataset.duration, 10);
  if (dd >= 1 && dd <= 30) currentDuration = dd;
}

let viewYear = currentPickup.getFullYear();
let viewMonth = currentPickup.getMonth();

const tglAmbilBox = document.getElementById("tglAmbilBox");
const tglAmbil = document.getElementById("tglAmbil");
const tglKembali = document.getElementById("tglKembali");
const calendarPopup = document.getElementById("calendarPopup");
const calMonthYear = document.getElementById("calMonthYear");
const calDaysGrid = document.getElementById("calDaysGrid");
const calPrev = document.getElementById("calPrev");
const calNext = document.getElementById("calNext");

const durasiToggle = document.getElementById("durasiToggle");
const durasiDropdown = document.getElementById("durasiDropdown");
const durasiList = document.getElementById("durasiList");

function updateReturnDate() {
  if (tglKembali) {
    const retDate = calcReturnDate(currentPickup, currentDuration);
    tglKembali.value = fmt(retDate);
  }
  // Sinkronkan ke input hidden agar ikut terkirim saat form "Cari" disubmit
  if (tglAmbilValue) tglAmbilValue.value = isoDate(currentPickup);
  if (durasiValue) durasiValue.value = String(currentDuration);
}

function renderDurasiList() {
  if (!durasiList) return;
  durasiList.innerHTML = "";
  for (let n = 2; n <= 30; n++) {
    const retDate = calcReturnDate(currentPickup, n);
    const li = document.createElement("li");
    li.innerHTML = `<span class="d-day">${n} Hari</span><br><span class="d-date">${fmt(retDate)}</span>`;
    li.addEventListener("click", () => {
      currentDuration = n;
      durasiToggle.firstChild.textContent = `${n} Hari `;
      updateReturnDate();
      durasiDropdown.classList.remove("open");
    });
    durasiList.appendChild(li);
  }
}

function renderCalendar(year, month) {
  if (!calDaysGrid || !calMonthYear) return;
  calMonthYear.textContent = `${BULAN_FULL[month]} ${year}`;

  if (year === today.getFullYear() && month <= today.getMonth()) {
    calPrev.classList.add("disabled");
  } else {
    calPrev.classList.remove("disabled");
  }

  calDaysGrid.innerHTML = "";

  const firstDay = new Date(year, month, 1).getDay(); // 0 is Sunday
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevMonthDays = new Date(year, month, 0).getDate();

  // Filler hari dari bulan sebelumnya
  for (let i = firstDay - 1; i >= 0; i--) {
    const el = document.createElement("div");
    el.className = "cal-day other-month disabled";
    el.textContent = prevMonthDays - i;
    calDaysGrid.appendChild(el);
  }

  // Hari-hari di bulan aktif
  for (let day = 1; day <= daysInMonth; day++) {
    const thisDate = new Date(year, month, day);
    const el = document.createElement("div");
    el.className = "cal-day";
    el.textContent = day;

    if (isPastDate(thisDate, today)) {
      el.classList.add("disabled");
    } else {
      if (isSameDate(thisDate, currentPickup)) {
        el.classList.add("active");
      }
      el.addEventListener("click", () => {
        currentPickup = new Date(year, month, day);
        if (tglAmbil) tglAmbil.value = fmt(currentPickup);
        updateReturnDate();
        renderDurasiList();
        renderCalendar(year, month);
        closeCalendar();
      });
    }
    calDaysGrid.appendChild(el);
  }

  // Filler hari bulan berikutnya
  const totalCells = firstDay + daysInMonth;
  const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
  for (let i = 1; i <= remaining; i++) {
    const el = document.createElement("div");
    el.className = "cal-day other-month disabled";
    el.textContent = i;
    calDaysGrid.appendChild(el);
  }
}

function openCalendar() {
  if (durasiDropdown) durasiDropdown.classList.remove("open");
  if (calendarPopup) calendarPopup.classList.add("open");
  if (tglAmbilBox) tglAmbilBox.classList.add("open");
}

function closeCalendar() {
  if (calendarPopup) calendarPopup.classList.remove("open");
  if (tglAmbilBox) tglAmbilBox.classList.remove("open");
}

if (tglAmbilBox) {
  tglAmbilBox.addEventListener("click", (e) => {
    e.stopPropagation();
    if (calendarPopup && calendarPopup.classList.contains("open")) {
      closeCalendar();
    } else {
      openCalendar();
    }
  });
}

if (calPrev) {
  calPrev.addEventListener("click", (e) => {
    e.stopPropagation();
    if (viewYear === today.getFullYear() && viewMonth <= today.getMonth()) return;
    viewMonth--;
    if (viewMonth < 0) {
      viewMonth = 11;
      viewYear--;
    }
    renderCalendar(viewYear, viewMonth);
  });
}

if (calNext) {
  calNext.addEventListener("click", (e) => {
    e.stopPropagation();
    viewMonth++;
    if (viewMonth > 11) {
      viewMonth = 0;
      viewYear++;
    }
    renderCalendar(viewYear, viewMonth);
  });
}

if (calendarPopup) {
  calendarPopup.addEventListener("click", (e) => e.stopPropagation());
}

if (durasiToggle) {
  durasiToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    closeCalendar();
    durasiDropdown.classList.toggle("open");
  });
}

document.addEventListener("click", (e) => {
  if (calendarPopup && !calendarPopup.contains(e.target) && tglAmbilBox && !tglAmbilBox.contains(e.target)) {
    closeCalendar();
  }
  if (durasiDropdown && !durasiDropdown.contains(e.target)) {
    durasiDropdown.classList.remove("open");
  }
});

// Inisialisasi awal
if (tglAmbil) {
  tglAmbil.value = fmt(currentPickup);
}
if (durasiToggle && durasiToggle.firstChild) {
  durasiToggle.firstChild.textContent = `${currentDuration} Hari `;
}
updateReturnDate();
renderDurasiList();
renderCalendar(viewYear, viewMonth);

// ---------- Dropdown kategori ----------
const kategoriItem = document.getElementById("kategoriItem");
if (kategoriItem) {
  const link = kategoriItem.querySelector(".nav-link");
  link.addEventListener("click", e => {
    e.preventDefault();
    kategoriItem.classList.toggle("open");
  });
  // hover di desktop
  kategoriItem.addEventListener("mouseenter", () => {
    kategoriItem.classList.add("open");
  });
  kategoriItem.addEventListener("mouseleave", () => {
    kategoriItem.classList.remove("open");
  });
  // tutup jika klik di luar
  document.addEventListener("click", e => {
    if (!kategoriItem.contains(e.target)) {
      kategoriItem.classList.remove("open");
    }
  });
}

// ---------- Sticky header + scroll-top ----------
const header = document.getElementById("header");
const scrollTop = document.getElementById("scrollTop");
function onScroll() {
  const y = window.scrollY;
  header.classList.toggle("stick", y > 80);
  scrollTop.classList.toggle("show", y > 400);
}
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();
scrollTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

// ---------- Hamburger (mobile) ----------
const hamburger = document.getElementById("hamburger");
const mainNav = document.getElementById("mainNav");
if (hamburger) {
  hamburger.addEventListener("click", e => {
    e.stopPropagation();
    mainNav.classList.toggle("open");
  });
  document.addEventListener("click", e => {
    if (!mainNav.contains(e.target)) mainNav.classList.remove("open");
  });
}

// ---------- Navigasi Login (Fallback Handlers) ----------
document.querySelectorAll(".login-link").forEach(btn => {
  btn.addEventListener("click", () => {
    window.location.href = "login.html";
  });
});

// ---------- Fade-in on scroll (pengganti wow.js) ----------
const io = new IntersectionObserver(entries => {
  entries.forEach(en => {
    if (en.isIntersecting) {
      en.target.classList.add("animated");
      io.unobserve(en.target);
    }
  });
}, { threshold: 0.1 });
document.querySelectorAll(".wow").forEach(el => io.observe(el));
