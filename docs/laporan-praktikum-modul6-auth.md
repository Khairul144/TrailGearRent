# LAPORAN PRAKTIKUM KEAMANAN — Modul VI (Adaptasi Django/PostgreSQL)

**Sistem:** TrailGear — Authentication & Access Control
**Tanggal uji:** 5–6 November 2026
**Lokasi:** `D:\Nyoba` · `http://127.0.0.1:8000`
**Acuan:** MODUL VI PRAKTIKUM — Konfigurasi Password Policy & Authentication (MySQL), dipetakan ke Django.

---

## 1. Environment

| Komponen | Nilai |
|---|---|
| OS | Windows 11 |
| Python | 3.14.5 (venv proyek) |
| Django | 6.1.3 |
| Database | PostgreSQL 18.6 — database `TrailGear_auth`, user `tg_user` |
| Server uji | `manage.py runserver 127.0.0.1:8000` (DEBUG=True, HTTP lokal) |
| Autentikasi | Django session authentication (tanpa JWT) |
| Pengujian HTTP | skrip Python (urllib + cookie jar) & browser |
| Pengujian otomatis | `manage.py test accounts` → **84 test, OK** |

## 2. System Under Test

Aplikasi `accounts`: custom user model (`accounts.User`), registrasi, login (username/email), logout, session, password validator, rate limiting, security event logging, role berbasis Django Groups (Customer/Cashier/Admin), proteksi dashboard per role.

## 3. Pemetaan Modul → TrailGear

| Konsep Modul VI (MySQL) | Padanan TrailGear (Django) | Status |
|---|---|---|
| `INSTALL PLUGIN validate_password` | `AUTH_PASSWORD_VALIDATORS` (8 validator) | Setara (dikonfigurasi di kode, bukan plugin DBMS) |
| `validate_password.length = 8` | `MinimumLengthValidator(min_length=8)` + `MaximumLengthValidator(128)` | Setara |
| `validate_password.policy = STRONG` | Uppercase + Lowercase + Digit + Symbol + Common + Similarity | Setara (lebih ketat: 4 kelas karakter) |
| `CREATE USER ... IDENTIFIED BY` | `POST /register/` → `User.objects.create_user()` + `set_password()` | Setara |
| `PASSWORD EXPIRE INTERVAL 30 DAY` | — | **NOT IMPLEMENTED** (tidak ada padanan langsung) |
| `FAILED_LOGIN_ATTEMPTS 3` / `PASSWORD_LOCK_TIME` | Rate limiting 5 gagal/10 menit (per IP + identitas) | **Berbeda** — throttle, bukan account lock |
| `mysql -u user -p` | `POST /login/` (session) | Setara |
| Hash password oleh DBMS | PBKDF2-SHA256 (1.500.000 iterasi) oleh Django | Setara |
| Grant/role MySQL | Django Groups + Permissions | Setara |

## 4. Audit Fitur

| Fitur | Ada? | Implementasi | Sesuai Modul? | Perlu Diuji? |
|---|---|---|---|---|
| Custom User Model | Ya | `accounts.User(AbstractUser)`, email unik, phone, address | Ya (adaptasi) | Ya |
| Registration | Ya | `views.register` + `RegistrationForm` | Ya | Ya |
| Login (username/email) | Ya | `EmailOrUsernameBackend` + `auth_login` | Ya | Ya |
| Logout | Ya | POST + CSRF (`views.logout_view`) | Ya | Ya |
| Password Hashing | Ya | PBKDF2-SHA256, salt otomatis | Ya | Ya |
| Password Validators | Ya | 8 validator (min 8, max 128, upper, lower, digit, symbol, common, similarity) | Ya (STRONG) | Ya |
| Password Policy | Ya | idem | Ya | Ya |
| Rate Limiting Registration | Ya | 3 / IP / 10 menit (FileBasedCache) | Improvisasi | Ya |
| Rate Limiting Login | Ya | 5 gagal / IP + identitas / 10 menit | Improvisasi | Ya |
| Failed Login Tracking | Ya | `SecurityEvent.LOGIN_FAILED` | Ya | Ya |
| Account Lock | **Tidak** | — (hanya rate limit sementara) | Tidak | Dokumentasi |
| Password Expiry | **Tidak** | — | Tidak (khas DBMS) | Dokumentasi |
| Security Event Logging | Ya | tabel `accounts_securityevent` + `logs/security.log` | Improvisasi | Ya |
| CSRF | Ya | `CsrfViewMiddleware`, semua form `{% csrf_token %}` | Improvisasi | Ya |
| Session Security | Ya | DB session, HttpOnly, SameSite=Lax, 12 jam | Improvisasi | Ya |
| Role/Permission | Ya | Groups Customer/Cashier/Admin | Improvisasi | Ya |
| Authorization | Ya | `@role_required` (RBAC) + ownership filter | Improvisasi | Ya |

### A. Wajib dari modul
Password policy (panjang + kompleksitas), penolakan password lemah, penerimaan password kuat, authentication login, uji login salah, password hashing tersimpan aman.

### B. Relevan tetapi perlu adaptasi
Failed login attempt (modul: account lock → TrailGear: rate limiting + event log), pembuatan user (modul: `CREATE USER` → TrailGear: registrasi web), pemeriksaan plugin password (→ deklarasi validator Django).

### C. Tidak relevan / berbeda fundamental
`validate_password.so`, `SHOW PLUGINS`, `SET GLOBAL`, `ALTER USER ... PASSWORD EXPIRE`, `FAILED_LOGIN_ATTEMPTS`/`PASSWORD_LOCK_TIME` sebagai atribut user MySQL, autentikasi DBMS (koneksi aplikasi memakai satu role `tg_user`).

### D. Improvisasi keamanan (tidak ada di modul)
CSRF, SQL injection, XSS, user enumeration, RBAC, session security, security event logging, rate limiting.

## 5. Test Matrix (hasil eksekusi nyata)

| No | Pengujian | Acuan | Expected | Actual | Status |
|---|---|---|---|---|---|
| 1 | Password `123` | Modul | Ditolak | HTTP 200 · "Kata sandi terlalu pendek. Harus mengandung setidaknya 8 karakter." | PASS |
| 2 | Password `password` | Modul | Ditolak | HTTP 200 · ditolak (terlalu umum/kompleksitas) | PASS |
| 3 | Tanpa simbol (`Password1`) | Modul | Ditolak | HTTP 200 · "Password harus mengandung minimal satu simbol" | PASS |
| 4 | Tanpa huruf kapital (`password1!`) | Modul | Ditolak | HTTP 200 · ditolak | PASS |
| 5 | Tanpa huruf kecil (`PASSWORD1!`) | Modul | Ditolak | HTTP 200 · ditolak | PASS |
| 6 | Tanpa angka (`Password!`) | Modul | Ditolak | HTTP 200 · ditolak | PASS |
| 7 | Konfirmasi berbeda | Modul | Ditolak | HTTP 200 · "Konfirmasi password tidak cocok." | PASS |
| 8 | Password kuat `TrailGear#2026` | Modul | Diterima | HTTP 302 → `/` (user dibuat) | PASS |
| 9 | Username duplikat | TrailGear | Ditolak | HTTP 200 · "Username sudah digunakan." | PASS |
| 10 | Email duplikat | TrailGear | Ditolak | HTTP 200 · "Email sudah terdaftar." | PASS |
| 11 | Email tidak valid (`bukan-email`) | TrailGear | Ditolak | HTTP 200 · validasi email Django | PASS |
| 12 | Login benar (username) | Modul | Berhasil | HTTP 302 → dashboard role | PASS |
| 13 | Login benar (email) | Modul | Berhasil | HTTP 302 → dashboard role | PASS |
| 14 | Login password salah | Modul | Ditolak | HTTP 200 · "Username/email atau password tidak valid." | PASS |
| 15 | User enumeration (ada vs tidak ada) | Improvisasi | Pesan identik | Keduanya: "Username/email atau password tidak valid." | PASS |
| 16 | POST tanpa token CSRF | Improvisasi | Ditolak | HTTP 403 Forbidden | PASS |
| 17 | SQL injection (`' OR 1=1 --`, `admin'--`, `' OR '1'='1`) | Improvisasi | Tidak bypass | Ketiganya HTTP 200 (login gagal, tidak ada bypass) | PASS |
| 18 | XSS `<script>alert('xss')</script>` di nama | Improvisasi | Ter-escape | Tampil sebagai teks; `innerHTML` tidak memuat script | PASS |
| 19 | Customer → `/dashboard/admin/` | Improvisasi | 403 | HTTP 403 | PASS |
| 20 | Customer → `/dashboard/cashier/` | Improvisasi | 403 | HTTP 403 | PASS |
| 21 | Cashier → `/dashboard/admin/` | Improvisasi | 403 | HTTP 403 | PASS |
| 22 | Cashier → `/dashboard/cashier/` | Improvisasi | 200 | HTTP 200 | PASS |
| 23 | Admin → `/dashboard/admin/` | Improvisasi | 200 | HTTP 200 | PASS |
| 24 | Admin → `/dashboard/cashier/` | Improvisasi | 200 | HTTP 200 | PASS |
| 25 | Dashboard tanpa login | Improvisasi | Redirect | HTTP 302 → `/login/?next=/dashboard/` | PASS |
| 26 | Session setelah logout | Improvisasi | Ditolak | Sebelum 200 → sesudah 302 | PASS |
| 27 | Atribut cookie session | Improvisasi | HttpOnly + SameSite | `HttpOnly`, `SameSite=Lax`, `Max-Age=43200`, `Secure=False` (HTTP lokal) | PASS |
| 28 | Login gagal 5× lalu ke-6 | Modul/TrailGear | Dibatasi | 200,200,200,200,200,**429** | PASS |
| 29 | Registrasi 3× lalu ke-4 | TrailGear | Dibatasi | 302,302,302,**429** | PASS |

**Total: 29 PASS / 0 FAIL.**

> Catatan kejujuran: pada run pertama, butir 27 tercatat FAIL karena *harness* Python tidak membaca `Set-Cookie` pada respons redirect. Setelah diperiksa langsung via header curl dan atribut cookie jar, hasil sebenarnya PASS (HttpOnly + SameSite=Lax). Hal ini dicatat sebagai keterbatasan alat ukur, bukan temuan aplikasi.

## 6. Bukti Password Hashing

```
 username | algoritma                | panjang | hash
----------+--------------------------+---------+--------------------------
 ujicoba  | pbkdf2_sha256$1500000$   |      89 | pbkdf2_sha256$1500000$...
 admin1   | pbkdf2_sha256$1500000$   |      89 | ...
 kasir1   | pbkdf2_sha256$1500000$   |      89 | ...
```
`select count(*) ... where password not like 'pbkdf2_%'` → **0** (tidak ada plaintext).

## 7. Security Event Logging (hasil uji)

| event_type | jumlah |
|---|---|
| REGISTER_SUCCESS | 7 |
| REGISTER_FAILED | 14 |
| LOGIN_SUCCESS | 15 |
| LOGIN_FAILED | 19 |
| LOGOUT | 7 |
| RATE_LIMIT_LOGIN | 2 |
| RATE_LIMIT_REGISTER | 2 |
| ACCESS_DENIED | 6 |

Kolom tersedia & terisi: `event_type`, `status`, `ip_address`, `user_agent`, `user`, `timestamp`, `description`.
Pemeriksaan kebocoran pada `logs/security.log`: password, token CSRF, dan `sessionid` → **0 kemunculan**. `description` hanya memuat nama field (mis. `invalid_fields=password_confirmation`), bukan nilainya.

## 8. Findings

### F1 — Tidak ada account lock (hanya rate limiting)
- **Severity:** Medium
- **Affected:** `accounts/ratelimit.py`, `views.login_view`
- **Evidence:** 6 percobaan gagal → `429`; akun tetap aktif, tidak terkunci.
- **Expected (modul):** akun terkunci setelah 3 gagal.
- **Actual:** throttle sementara per IP + identitas, TTL 10 menit, tanpa status terkunci.
- **Risk:** penyerang terdistribusi (banyak IP) bisa menebak password tanpa memicu batas per-IP.
- **Recommendation:** tambah lockout bertingkat (mis. 10 gagal/akun → kunci 15 menit + notifikasi), atau tetap rate limit namun tambah CAPTCHA setelah N gagal.
- **Status:** NOT IMPLEMENTED (by design, terverifikasi).

### F2 — Password expiry tidak ada
- **Severity:** Low
- **Affected:** `accounts.User`
- **Evidence:** tidak ada field `password_changed_at`; `PASSWORD EXPIRE` tidak punya padanan.
- **Risk:** password lama tetap valid selamanya.
- **Recommendation:** tambah `password_changed_at` + cek umur di login, atau pakai kebijakan rotasi bila dibutuhkan organisasi.
- **Status:** NOT IMPLEMENTED (khas DBMS, tidak dipaksakan).

### F3 — 403 membocorkan keberadaan route sensitif
- **Severity:** Low
- **Affected:** `accounts/permissions.py`
- **Evidence:** Customer mendapat halaman 403 "Akses ditolak" pada `/dashboard/admin/`.
- **Risk:** enumerasi endpoint admin/keamanan.
- **Recommendation:** kembalikan 404 untuk area admin (`@role_required(..., hide=True)`).
- **Status:** OPEN (opsional).

### F4 — Cookie `Secure` belum aktif (development)
- **Severity:** Info (dev) / Medium (produksi)
- **Evidence:** `Secure=False`, `Max-Age=43200`, `SESSION_COOKIE_SECURE=env_bool("DJANGO_SECURE_COOKIES", False)`.
- **Recommendation:** set `DJANGO_SECURE_COOKIES=True`, `DJANGO_SECURE_SSL_REDIRECT=True`, HSTS saat HTTPS.
- **Status:** Konfigurasi sengaja untuk localhost HTTP.

### F5 — Rate limit memakai REMOTE_ADDR saja
- **Severity:** Low
- **Evidence:** `client_ip()` sengaja mengabaikan `X-Forwarded-For`.
- **Risk:** di belakang reverse proxy, semua user berbagi satu bucket; sebaliknya, penyerang yang mengganti IP bisa melewati batas.
- **Recommendation:** aktifkan pembacaan XFF hanya dari proxy tepercaya (`USE_X_FORWARDED_HOST` + daftar proxy).
- **Status:** OPEN (terdokumentasi).

### F6 — Log menyimpan identifier yang diketik user
- **Severity:** Info
- **Evidence:** `description = "identifier='target_lock_test'"`.
- **Risk:** PII ringan di log bila user salah ketik email orang lain.
- **Recommendation:** hash identifier di log, atau simpan hanya 3 karakter pertama.
- **Status:** OPEN (opsional).

### F7 — DEBUG=True
- **Severity:** Info (dev)
- **Evidence:** halaman 403 menampilkan "🐴 403 Forbidden" versi debug.
- **Recommendation:** `DJANGO_DEBUG=False` di produksi.
- **Status:** Sesuai lingkungan praktikum.

## 9. Rekomendasi Ringkas

1. Implementasi account lockout bertingkat (internal Django, tanpa layanan pihak ketiga).
2. Tambah `password_changed_at` + kebijakan rotasi bila diperlukan.
3. Masking 404 untuk route admin.
4. Aktifkan `Secure`/HSTS/SSL redirect saat produksi.
5. Pertimbangkan hashing identifier pada log.
6. Tambah test otomatis untuk account lock & password age bila fitur dibuat.

## 10. Final Security Assessment

| Aspek | Nilai | Keterangan |
|---|---|---|
| Password policy | **Baik** | 8 validator, 4 kelas karakter, tolak password umum & mirip identitas |
| Password storage | **Baik** | PBKDF2-SHA256 1,5 juta iterasi + salt, tidak ada plaintext |
| Authentication | **Baik** | Username/email, pesan generik, session rotation |
| Brute force resistance | **Cukup** | Rate limit per IP+identitas; belum ada lockout akun |
| Session security | **Baik** | HttpOnly, SameSite=Lax, DB session, logout invalidasi |
| Authorization | **Baik** | RBAC backend-side, 403 konsisten, ownership filter |
| Input handling | **Baik** | ORM (SQLi aman), autoescape template (XSS aman) |
| Auditability | **Baik** | 8 tipe event + IP/UA/timestamp, tanpa data sensitif |

**Kesimpulan:** mekanisme authentication TrailGear berjalan sesuai kebijakan yang ditetapkan dan seluruh 29 pengujian memberikan hasil yang diharapkan. Sistem **tidak** dapat dinyatakan "100% aman": dua kontrol khas modul MySQL (account lock dan password expiry) tidak tersedia, dan tiga item konfigurasi (cookie Secure, masking 403, XFF) masih terbuka untuk produksi.
