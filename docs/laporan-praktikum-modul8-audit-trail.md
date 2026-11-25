# Laporan Praktikum Modul VIII: Konfigurasi Audit Trail dan Logging Database — TrailGear (Django + PostgreSQL 18)

**Identitas Lingkungan Lab:**
- **Aplikasi:** TrailGear (Platform Penyewaan Peralatan Outdoor — `Django 6.1`)
- **DBMS:** PostgreSQL 18.6 (`127.0.0.1:5432`, Database `TrailGear_auth`, TLSv1.3 aktif)
- **Sistem Operasi:** Windows 11 (PowerShell 5.1)
- **Tanggal Eksekusi:** 26 November 2026
- **Direktori Bukti Mentah:** [praktikum_modul8/ringkasan.md](file:///d:/Nyoba/praktikum_modul8/ringkasan.md)

---

## 1. Audit Kondisi Awal (*Baseline Assessment*)

Sebelum melakukan perubahan apa pun, dilakukan inspeksi langsung terhadap kode sumber (`accounts/`, `catalog/`, `rentals/`, `config/settings.py`), file log (`logs/security.log`), dan konfigurasi *live* PostgreSQL 18 (`TrailGear_auth`). Bukti baseline tersimpan di [00_baseline_audit.txt](file:///d:/Nyoba/praktikum_modul8/00_baseline_audit.txt).

### 1.1 Lapisan Pencatatan yang Sudah Tersedia di TrailGear
1. **Lapisan 1 — Application Security Event Logging (Aktif & Matang):**
   - Mekanisme *dual-sink* melalui `log_event()` pada [accounts/security.py](file:///d:/Nyoba/accounts/security.py) yang menulis secara bersamaan ke tabel PostgreSQL `accounts_securityevent` ([accounts/models.py](file:///d:/Nyoba/accounts/models.py#L160-L245)) dan file rotasi `d:\Nyoba\logs\security.log` (`RotatingFileHandler`, maks `5 MB`, `3` backup, UTF-8).
   - Pada kondisi awal sudah terdapat **18 tipe event** yang mencakup autentikasi (`REGISTER_*`, `LOGIN_*`, `LOGOUT`, `PASSWORD_CHANGED`), proteksi brute-force (`RATE_LIMIT_*`, `ACCOUNT_LOCKED`, `ACCOUNT_DISABLED`), RBAC/IDOR (`ACCESS_DENIED`), serta alur bisnis & Maker–Checker (`PAYMENT_PROOF_*`, `ORDER_CANCELLED`, `ORDER_APPROVED`, `MAKER_CHECKER_VIOLATION`, `RETURN_COMPLETED`, `FINE_PAID`).
   - Dashboard monitoring `/dashboard/admin/security/` sudah tersedia lengkap dengan filter `status`/`event_type`, panel status parameter audit DBMS, serta laporan *User Access Review (UAR)*. Di Django Admin, `SecurityEventAdmin` bersifat *append-only/read-only*.
2. **Lapisan 2 — Business Inventory & Django Admin Audit (Aktif):**
   - `catalog_inventory_log` mencatat seluruh perubahan stok (`167` baris baseline).
   - `django_admin_log` mencatat aksi di `/admin/` (`0` baris baseline).
3. **Lapisan 3 — DBMS Audit Logging PostgreSQL 18 (Awalnya NONAKTIF):**
   - `logging_collector = off`
   - `log_statement = none`
   - `log_connections = ''` *(off)*
   - `log_disconnections = off`
   - `log_line_prefix = '%m [%p] '` *(belum memuat user `%u`, database `%d`, dan IP client `%r`)*
   - `pg_current_logfile() = ''` *(kosong)*

### 1.2 Pemetaan Kondisi Awal terhadap Indikator Modul VIII
- **Sudah terpenuhi sebelum eksekusi:** Audit trail level aplikasi (`SecurityEvent`, `InventoryLog`), antarmuka pembacaan log (`/dashboard/admin/security/`), proteksi ORM terhadap SQLi, auto-escaping XSS, dan proteksi RBAC/IDOR/Maker–Checker.
- **Belum terpenuhi sebelum eksekusi:** Aktivasi logging di level DBMS PostgreSQL 18 (Indikator #1 Modul VIII), pencatatan aksi sensitif Admin (`role/status/unlock/reset rate limit`), serta persistensi file log untuk kegagalan CSRF/HTTP error.

---

## 2. Gap Analysis

### A. Sudah Tersedia -> Digunakan & Diuji Langsung
- Dual-sink `accounts_securityevent` + `logs/security.log` (18 event awal).
- `catalog_inventory_log` untuk pelacakan mutasi stok.
- Dashboard `/dashboard/admin/security/` & proteksi *append-only* `SecurityEventAdmin`.
- Proteksi aplikasi terhadap SQLi (Django ORM parameterized queries), XSS (auto-escaping), CSRF, anti-enumeration, RBAC, IDOR, dan Maker–Checker.

### B. Belum Tersedia tetapi Relevan -> Masuk Rencana Implementasi / Rekomendasi

| ID Gap | Lapisan | Kekurangan Terverifikasi | Status pada Praktikum Ini |
| :--- | :---: | :--- | :--- |
| **G1** | DBMS PostgreSQL 18 | `logging_collector=off`, `log_statement=none`, `log_connections=off`, `log_disconnections=off`, `log_line_prefix` tanpa `%u@%d %r`. | **Diimplementasikan (Tahap 1)** — `log_statement=all`, `log_connections=on`, `log_disconnections=on`, `log_line_prefix` aktif seketika; `logging_collector=on` tersimpan di `postgresql.auto.conf` (menunggu restart service Admin untuk pindah ke file `.log`). |
| **G2** | Aplikasi (`accounts/views.py`) | Aksi sensitif Admin (`admin_user_manage` unlock & ubah role/aktif, `admin_user_toggle`, `admin_reset_ratelimit`) belum memanggil `log_event()`. | **Diimplementasikan (Tahap 2)** — ditutup dengan event `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE` + unit test otomatis. |
| **G3** | Aplikasi (`rentals/views.py`) | `checkout` belum mencatat `ORDER_CREATED` ke `SecurityEvent`; akses keranjang user lain hanya mengembalikan `404`. | **Dicatat sebagai rekomendasi lanjutan** (transaksi tetap tercatat di `rentals_rental_order` & `catalog_inventory_log`). |
| **G4** | Aplikasi (Session Replay) | Akses URL protected setelah logout / dengan cookie `sessionid` lama atau palsu hanya redirect `302` tanpa event di `SecurityEvent`. | **Dipertahankan untuk uji *blind spot* jujur** (dan berhasil terdeteksi di lapisan DBMS `SELECT django_session` 3 ms pasca-`DELETE`). |
| **G5** | Aplikasi (Input Probing) | Payload SQLi/XSS pada pencarian katalog publik (`/products/?q=`) dan form profil (`/settings/`) ditahan/di-escape tanpa alert khusus di `SecurityEvent`. | **Dipertahankan untuk uji *blind spot* jujur** (dan berhasil terdeteksi di lapisan DBMS `log_statement=all`). |
| **G6** | Konfigurasi Logging (`settings.py`) | Logger `django.request` hanya ke `console` dan `django.security.csrf` belum diarahkan ke `security_file`. | **Diimplementasikan (Tahap 2)** — diverifikasi langsung menulis `WARNING | django.security.csrf | Forbidden (CSRF cookie not set.)` ke `logs/security.log`. |

### C. Tidak Relevan (Perbedaan MySQL pada Modul vs Django + PostgreSQL 18)
1. `mysql -u root -p` -> diganti `psql -h 127.0.0.1 -U postgres -d TrailGear_auth`.
2. `SHOW VARIABLES LIKE 'general_log'` & `SET GLOBAL general_log = 'ON'` -> di PostgreSQL menggunakan `ALTER SYSTEM SET log_statement = 'all'` (setara *general log* selama praktikum; disarankan `'mod'` di produksi) bersama `logging_collector = 'on'`, `log_connections = 'on'`, dan `log_disconnections = 'on'`.
3. `SHOW VARIABLES LIKE 'general_log_file'` -> di PostgreSQL menggunakan `SHOW data_directory;`, `SHOW log_directory;`, `SHOW log_filename;`, dan `SELECT pg_current_logfile();`.
4. `INSTALL PLUGIN audit_log SONAME 'audit_log.so'` -> plugin biner MySQL/MariaDB. Pada PostgreSQL padanannya adalah `pgaudit`, namun distribusi EnterpriseDB PostgreSQL 18 Windows pada mesin lab tidak menyertakan `pgaudit` di `pg_available_extensions`. Kebutuhan audit dipenuhi secara setara melalui **PostgreSQL Native Audit Logging + Application Audit Trail (`accounts_securityevent` & `catalog_inventory_log`)**.
5. `cat` / `tail -f /var/lib/mysql/*.log` -> pada Windows PowerShell menggunakan `Get-EventLog -LogName Application -Source "*PostgreSQL*"`, `Get-Content -Tail`, dan `Select-String`.

---

## 3. Implementasi yang Dikerjakan

### 3.1 Tahap 1 — Aktivasi Audit Logging DBMS PostgreSQL 18 (Menutup Gap G1)
Perintah dijalankan via `psql` (`postgres@TrailGear_auth`) dan hasilnya terekam pada [01_aktivasi_dbms_logging.txt](file:///d:/Nyoba/praktikum_modul8/01_aktivasi_dbms_logging.txt):

```sql
ALTER SYSTEM SET logging_collector = 'on';
ALTER SYSTEM SET log_directory = 'log';
ALTER SYSTEM SET log_filename = 'postgresql-%Y-%m-%d.log';
ALTER SYSTEM SET log_statement = 'all';
ALTER SYSTEM SET log_connections = 'on';
ALTER SYSTEM SET log_disconnections = 'on';
ALTER SYSTEM SET log_line_prefix = '%m [%p] %q%u@%d %r ';
SELECT pg_reload_conf();
```

**Hasil Verifikasi Parameter Setelah Reload:**
| Parameter | Sebelum | Sesudah `pg_reload_conf()` | Keterangan |
| :--- | :--- | :--- | :--- |
| `log_statement` | `none` | **`all`** | Aktif seketika — seluruh `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DDL` terekam. |
| `log_connections` | *(off)* | **`on`** | Aktif seketika — mencatat setiap upaya koneksi (sukses maupun `FATAL` gagal auth). |
| `log_disconnections` | `off` | **`on`** | Aktif seketika — mencatat durasi sesi saat klien memutus koneksi. |
| `log_line_prefix` | `%m [%p] ` | **`%m [%p] %q%u@%d %r `** | Aktif seketika — menampilkan timestamp ms, PID, `user@db`, dan `IP(port)` klien. |
| `log_filename` | `postgresql-%Y-%m-%d_%H%M%S.log` | **`postgresql-%Y-%m-%d.log`** | Tersimpan di `postgresql.auto.conf`. |
| `logging_collector` | `off` | `off` *(tertulis `on` di `postgresql.auto.conf`)* | Membutuhkan restart service Windows (`Restart-Service postgresql-x64-18` pada PowerShell Administrator) agar log berpindah dari Windows Application Event Log ke file `D:\Apps\PostgreSQL18\data\log\postgresql-YYYY-MM-DD.log`. Selama belum direstart, seluruh log tetap aktif terekam penuh di Windows Application Event Log (`Source: PostgreSQL`). |

### 3.2 Tahap 2 — Penguatan Audit Trail Aplikasi & CSRF File Logging (Menutup Gap G2 & G6)
Tidak ada sistem logging duplikat yang dibuat; seluruh penguatan memanfaatkan `accounts.security.log_event()` dan handler `security_file` yang sudah ada:
1. **[accounts/models.py](file:///d:/Nyoba/accounts/models.py#L185-L209):** Menambahkan konstanta dan pilihan event `ADMIN_USER_UPDATED` (`Admin mengubah role/status akun`) dan `ADMIN_SECURITY_OVERRIDE` (`Admin membuka blokir/reset keamanan`), diikuti migrasi [0011_alter_securityevent_event_type.py](file:///d:/Nyoba/accounts/migrations/0011_alter_securityevent_event_type.py) yang telah diterapkan (`migrate` OK).
2. **[accounts/views.py](file:///d:/Nyoba/accounts/views.py#L558-L695) & [accounts/views.py](file:///d:/Nyoba/accounts/views.py#L1020-L1076):** Menambahkan pemanggilan `log_event()` pada:
   - `admin_user_manage` (`action == "unlock"` -> `ADMIN_SECURITY_OVERRIDE`; `action == "profile_role"` -> `ADMIN_USER_UPDATED` mencatat `role=old->new` dan `active=old->new`),
   - `admin_user_toggle` (`ADMIN_USER_UPDATED` mencatat `action=toggle_active`),
   - `admin_reset_ratelimit` (`mode == "all"`, `unlock_user_id`, dan `ip` -> `ADMIN_SECURITY_OVERRIDE`).
3. **[config/settings.py](file:///d:/Nyoba/config/settings.py#L289-L299):** Menambahkan handler `"security_file"` pada logger `django.request` (`level: ERROR`) dan menambahkan logger `django.security.csrf` (`handlers: ["security_file", "console"]`, `level: WARNING`).
4. **[accounts/tests.py](file:///d:/Nyoba/accounts/tests.py#L1575-L1631):** Menambahkan verifikasi unit test `ADMIN_SECURITY_OVERRIDE` dan `test_admin_user_role_change_and_toggle_are_logged`.

**Verifikasi Unit Test & CSRF Logging:**
- `python manage.py check` -> `System check identified no issues (0 silenced).`
- `python manage.py test accounts.tests.AdminUserManageAndRateLimitResetTests accounts.tests.UserAccessReviewTests -v 2` -> **7 tests OK** (`50.989s`).
- Uji kirim `POST /login/` tanpa cookie CSRF (`enforce_csrf_checks=True`) menghasilkan `HTTP 403` dan menulis baris persisten ke `logs/security.log`:
  `2026-11-26 00:43:33,788 | WARNING | django.security.csrf | Forbidden (CSRF cookie not set.): /login/`

---

## 4 & 5. Hasil Eksekusi Skenario Simulasi Attacker & Matriks Analisis

Seluruh 19 skenario attacker (`A1–A3`, `B1–B3`, `C1–C3`, `D1–D4`, `E1–E3`, `F1–F3`) ditambah 1 skenario verifikasi penutupan Gap G2 (`G2-VERIFY`) dijalankan secara aman pada akun uji terisolasi (`m8_attacker`, `m8_victim`, `m8_disabled`), pesanan uji sementara (`TG-20261126-UT2Z` & `TG-20261126-QNTA`), serta tabel dummy `uji_audit_tmp`. Bukti terstruktur tersimpan pada [hasil_skenario.json](file:///d:/Nyoba/praktikum_modul8/hasil_skenario.json), [02_aktivitas_dbms_f1_f3.txt](file:///d:/Nyoba/praktikum_modul8/02_aktivitas_dbms_f1_f3.txt), dan [03_rekap_security_events.txt](file:///d:/Nyoba/praktikum_modul8/03_rekap_security_events.txt).

| Kode | Attacker Action | Target | Respons Aktual Aplikasi / DBMS | Kontrol Keamanan yang Bekerja | Audit Log / Event Aktual yang Tercatat | Informasi Tercatat | Deteksi dari Log? | Status | Severity (Jika Lemah) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **A1** | Brute-force gagal 6× (`127.0.0.1`) + 5× (`10.0.0.99`) pada `m8_victim` | `POST /login/` | `HTTP [200,200,200,200,200,429, 200,200,200,200,200]`, `locked=True` | `ratelimit.login_blocked()` + `User.register_failed_login()` | `LOGIN_FAILED` (10×), `RATE_LIMIT_LOGIN[BLOCKED]` (`ip=127.0.0.1`), `ACCOUNT_LOCKED[BLOCKED]` (`user=m8_victim`, `ip=10.0.0.99`, `threshold=10 durasi=15menit`) | Timestamp, IP, `user_id`, threshold & durasi kunci | **Ya** (App DB + `security.log`) | **PASS** | High |
| **A2** | Bandingkan login username terdaftar (`m8_attacker`) vs fiktif (`ghost_user_9999`) | `POST /login/` | Keduanya `HTTP 200`, pesan identik `"Username/email atau password tidak valid."` | Pesan error generik + dummy password hashing | 2× `LOGIN_FAILED[FAILURE]` (`user=None`, `ip=127.0.0.1`, `identifier='m8_attacker'` & `'ghost_user_9999'`) | Timestamp, IP, identifier uji | **Ya** (pola enumerasi per IP) | **PASS** | Medium |
| **A3** | Login dgn password benar ke akun nonaktif (`m8_disabled`) & terkunci (`m8_victim`) | `POST /login/` | Keduanya `HTTP 200`, ditolak tanpa sesi aktif | Cek `is_active` & `is_locked` sebelum autentikasi selesai | `ACCOUNT_DISABLED[FAILURE]` (`user=m8_disabled`), `LOGIN_FAILED` (`Akun terkunci sementara; login ditolak.`, `user=m8_victim`) | Timestamp, `user_id`, IP, status akun | **Ya** | **PASS** | Medium |
| **B1** | Customer (`m8_attacker`) akses langsung URL Kasir (3 endpoint) | `/dashboard/cashier/`, `/dashboard/orders/`, `/lookup/` | `HTTP [403, 403, 403]` | `@role_required(ROLE_CASHIER, ROLE_ADMIN)` | 3× `ACCESS_DENIED[BLOCKED]` (`user=m8_attacker`, `role=Customer butuh=Cashier,Admin`) | Timestamp, `user_id`, IP, path, role | **Ya** | **PASS** | High |
| **B2** | Customer (`m8_attacker`) akses langsung URL Admin (3 endpoint) | `/dashboard/admin/`, `/security/`, `/users/add/` | `HTTP [403, 403, 403]` | `@role_required(ROLE_ADMIN)` | 3× `ACCESS_DENIED[BLOCKED]` (`user=m8_attacker`, `role=Customer butuh=Admin`) | Timestamp, `user_id`, IP, path, role | **Ya** | **PASS** | Critical |
| **B3** | Cashier (`kasir1`) akses langsung URL & aksi Admin | `/dashboard/admin/`, `/users/`, `POST /reset-ratelimit/` | `HTTP [403, 403, 403]` | `@role_required(ROLE_ADMIN)` | 3× `ACCESS_DENIED[BLOCKED]` (`user=kasir1`, `role=Cashier butuh=Admin`) | Timestamp, `user_id`, IP, path, role | **Ya** | **PASS** | High |
| **C1** | SQLi payload `' OR 1=1 --` di form login | `POST /login/` | `HTTP 200`, gagal login (tidak bypass) | Django ORM parameterized query (`UPPER(''' OR 1=1 --')`) | App: `LOGIN_FAILED[FAILURE]` (`identifier="' OR 1=1 --"`); DBMS: `SELECT` ter-escape aman | Timestamp, IP, payload mentah di `description` & SQL DBMS | **Ya** (App + DBMS) | **PASS** | Critical |
| **C2** | SQLi `UNION SELECT` di pencarian katalog | `GET /products/?q=' OR '1'='1' UNION SELECT...` | `HTTP 200`, 0 produk, tidak error 500, tidak bocor `pbkdf2_sha256` | Django ORM `Q(...__icontains=query)` | **App: tidak ada event**; DBMS: query `SELECT ... LIKE` terekam karena `log_statement=all` | Teks query SQL di log DBMS | **Tidak di App / Ya di DBMS** *(Blind Spot G5)* | **PASS (Cegah)** | Medium |
| **C3** | Reflected XSS (`<script>alert('xss')</script>`) & Stored XSS (`<img src=x onerror=alert(1)>`) | `GET /products/`, `POST /settings/` | `HTTP 200`, keduanya ter-escape (`&lt;script&gt;`, `&lt;img`) | Django Template Auto-Escaping | **App: tidak ada event**; DBMS: `UPDATE "accounts_user" SET ... "first_name" = '<img src=x onerror=alert(1)>'` tercatat (`00:41:18.780`) | Statement `UPDATE` di log DBMS | **Tidak di App / Ya di DBMS** *(Blind Spot G5)* | **PASS (Cegah)** | Medium |
| **D1** | IDOR Read: `m8_attacker` buka detail & bukti bayar `TG-20261126-UT2Z` milik `m8_victim` | `GET /orders/<kode>/` & `/proof/` | `detail=403`, `proof=403` | Verifikasi kepemilikan `order.user_id != request.user.pk` | 2× `ACCESS_DENIED[BLOCKED]` (`order_detail ditolak`, `proof_file ditolak`) | Timestamp, `user_id`, IP, kode order | **Ya** | **PASS** | High |
| **D2** | IDOR Write: `m8_attacker` batalkan & unggah bukti pesanan `m8_victim` | `POST /orders/<kode>/cancel/` & `/upload-proof/` | `cancel=403`, `upload=403`; status tetap `MENUNGGU_PEMBAYARAN` | Verifikasi kepemilikan + transaksi atomik | 2× `ACCESS_DENIED[BLOCKED]` (`customer_cancel IDOR`, `upload_proof IDOR`) | Timestamp, `user_id`, IP, kode order | **Ya** | **PASS** | High |
| **D3** | Customer konfirmasi order + Kasir *self-approve* pesanan sendiri (`TG-20261126-QNTA`) | `POST /dashboard/orders/<kode>/confirm/` | `customer=403`, `kasir_self=302` (ditolak; status tetap `MENUNGGU_PEMBAYARAN`) | `@role_required` + kontrol *Separation of Duties* (Maker != Checker) | `ACCESS_DENIED` (Customer) + `MAKER_CHECKER_VIOLATION[BLOCKED]` (`user=kasir1`, `maker=2 checker=2 action=confirm`) | Timestamp, order, maker, checker, action, IP | **Ya** | **PASS** | High |
| **D4** | Customer & Cashier akses halaman kelola produk Admin & `/admin/` | `/dashboard/admin/products/` & `/admin/catalog/product/1/change/` | Dashboard: `403`, `403`; Django Admin: `302` redirect `/admin/login/` | `@role_required(ROLE_ADMIN)` & `is_staff=False` | 2× `ACCESS_DENIED[BLOCKED]` untuk `/dashboard/admin/products/`; redirect `/admin/` tidak masuk `SecurityEvent` | Timestamp, `user_id`, role, path | **Ya (Dashboard) / Tidak (`/admin/` 302)** | **PASS** | Medium |
| **G2-VERIFY** | Verifikasi Tahap 2: Admin toggle aktif akun & reset rate limit IP `10.0.0.99` | `POST /dashboard/admin/users/<id>/toggle/` & `/reset-ratelimit/` | `HTTP 302` | `@role_required(ROLE_ADMIN)` + `log_event()` baru | 2× `ADMIN_USER_UPDATED[SUCCESS]` (`toggle_active`) + 1× `ADMIN_SECURITY_OVERRIDE[SUCCESS]` (`reset_ratelimit_ip target_ip=10.0.0.99`) | Timestamp, admin `user_id`, target user/IP, perubahan status | **Ya (Gap G2 Tertutup)** | **PASS** | Info |
| **E1** | Akses `/settings/` segera sesudah `POST /logout/` | `POST /logout/` -> `GET /settings/` | `logout=302`, `after_logout=302` -> `/login/?next=/settings/` | `auth_logout()` hapus sesi + `@login_required` | `LOGOUT[SUCCESS]` tercatat; redirect `302` pasca-logout tidak tercatat di `SecurityEvent` | `user_id`, IP, timestamp logout | **Parsial** *(Blind Spot G4)* | **PASS (Kontrol)** | Low |
| **E2** | Replay cookie `sessionid` lama pasca-logout | `GET /settings/` + `Cookie: sessionid=<lama>` | `HTTP 302` -> `/login/?next=/settings/` | Row sesi telah dihapus dari `django_session` | **App: tidak ada event**; DBMS: tercatat `SELECT django_session` pasca-`DELETE` (diuji di Stage 6b) | Query lookup `session_key` di log DBMS | **Tidak di App / Ya di DBMS** *(Blind Spot G4)* | **PASS (Kontrol)** | Medium |
| **E3** | Kirim cookie `sessionid` palsu (`forged_invalid_session_token_12345`) | `GET /dashboard/admin/` | `HTTP 302` -> `/login/?next=/dashboard/admin/` | Session lookup gagal -> `AnonymousUser` | **App: tidak ada event** | Tidak tercatat di `SecurityEvent` | **Tidak di App** *(Blind Spot G4)* | **PASS (Kontrol)** | Low |
| **F1** | Aktivitas normal DBMS: `CREATE`/`INSERT`/`SELECT` `uji_audit_tmp` & `SELECT catalog_product` | PostgreSQL `TrailGear_auth` | `psql exit=0`, 1 row inserted & terbaca | Hak akses standar + `log_statement=all` | PostgreSQL Log (`00:41:22.635`–`.733`): `LOG: statement: CREATE TABLE ...`, `INSERT INTO uji_audit_tmp ...`, `SELECT ...` | Timestamp ms, PID `10648`, `postgres@TrailGear_auth`, `127.0.0.1(60528)`, SQL | **Ya (PostgreSQL Log)** | **PASS** | Info |
| **F2** | Destruktif aman: `DROP TABLE uji_audit_tmp` + `SET ROLE role_kasir_db; DELETE FROM accounts_securityevent;` | PostgreSQL `TrailGear_auth` | `DROP TABLE` sukses pada tabel dummy; `DELETE` ditolak `ERROR: permission denied` | `REVOKE DELETE` pada `role_kasir_db` + `log_statement=all` | PostgreSQL Log: `00:41:22.817 LOG: statement: DROP TABLE uji_audit_tmp;` & `00:41:22.906 ERROR: permission denied for table accounts_securityevent` | Timestamp ms, PID, user DBMS, IP:port, statement & pesan `ERROR` | **Ya (PostgreSQL Log)** | **PASS** | Critical |
| **F3** | Login gagal langsung ke DBMS (`psql -U normal_user` password salah) | PostgreSQL `127.0.0.1:5432` | `psql exit=2`, `FATAL: password authentication failed` | `scram-sha-256` di `pg_hba.conf` baris 125 + `log_connections=on` | PostgreSQL Log (`00:41:22.980` & `00:41:23.144`): `FATAL: password authentication failed for user "normal_user"` + detail baris `pg_hba.conf` | Timestamp ms, PID, `normal_user@TrailGear_auth`, IP:port, aturan `pg_hba.conf` | **Ya (PostgreSQL Log)** | **PASS** | High |

**Rekap Agregasi `accounts_securityevent` Selama Sesi Simulasi ([03_rekap_security_events.txt](file:///d:/Nyoba/praktikum_modul8/03_rekap_security_events.txt)):** Total **50 baris** dari **10 tipe event** (`ACCESS_DENIED`: 21, `LOGIN_FAILED`: 18, `ADMIN_USER_UPDATED`: 2, `LOGIN_SUCCESS`: 2, `LOGOUT`: 2, `ACCOUNT_DISABLED`: 1, `ACCOUNT_LOCKED`: 1, `ADMIN_SECURITY_OVERRIDE`: 1, `MAKER_CHECKER_VIOLATION`: 1, `RATE_LIMIT_LOGIN`: 1).

---

## 6. Korelasi Serangan Berantai (*Multi-Stage Attack Chain & Incident Reconstruction*)

Simulasi serangan berantai 6 tahap dijalankan dari satu IP khusus pengujian **`198.51.100.77`** (RFC 5737) oleh akun `m8_attacker` (`user_id=6`, role `Customer`). Hasil query SQL korelasi tersimpan di [04_korelasi_serangan_berantai.txt](file:///d:/Nyoba/praktikum_modul8/04_korelasi_serangan_berantai.txt) dan dicocokkan silang dengan log PostgreSQL pada [05_log_postgresql_dbms.txt](file:///d:/Nyoba/praktikum_modul8/05_log_postgresql_dbms.txt).

### 6.1 Linimasa Rekonstruksi Lintas-Lapisan (Aplikasi + DBMS)

| Waktu (WIB) | Tahap | Sumber Log | Aktor / DB User | Event / Statement Aktual | Analisis Forensik |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `00:41:28.765` | 1 | App DB + `security.log` | `anonymous` (`198.51.100.77`) | `LOGIN_FAILED` (`identifier='m8_attacker'`) | Tebakan password #1 gagal. |
| `00:41:34.634` | 1 | App DB + `security.log` | `anonymous` (`198.51.100.77`) | `LOGIN_FAILED` (`identifier='m8_attacker'`) | Tebakan password #2 gagal. |
| `00:41:40.590` | 1 | App DB + `security.log` | `anonymous` (`198.51.100.77`) | `LOGIN_FAILED` (`identifier='m8_attacker'`) | Tebakan password #3 gagal. |
| `00:41:43.182` | 2 | App DB + `security.log` | `m8_attacker` (`198.51.100.77`) | `LOGIN_SUCCESS` (`user_id=6`) | Aktor berhasil masuk; IP sama mengaitkan 3 kegagalan sebelumnya ke `m8_attacker`. |
| `00:41:43.209` | 3 | App DB + `security.log` | `m8_attacker` | `ACCESS_DENIED` (`path=/dashboard/cashier/ role=Customer butuh=Cashier,Admin`) | Upaya eskalasi hak akses ke dashboard Kasir diblokir. |
| `00:41:43.228` | 3 | App DB + `security.log` | `m8_attacker` | `ACCESS_DENIED` (`path=/dashboard/admin/security/ role=Customer butuh=Admin`) | Upaya mengintip halaman log keamanan Admin diblokir. |
| `00:41:43.269` | 4 | App DB + `security.log` | `m8_attacker` | `ACCESS_DENIED` (`order_detail ditolak order=TG-20261126-UT2Z`) | Percobaan IDOR membaca pesanan milik `m8_victim`. |
| `00:41:43.282` | 4 | App DB + `security.log` | `m8_attacker` | `ACCESS_DENIED` (`customer_cancel IDOR order=TG-20261126-UT2Z`) | Percobaan IDOR membatalkan pesanan milik `m8_victim`. |
| `00:41:43.301` | 4 | App DB + `security.log` | `m8_attacker` | `ACCESS_DENIED` (`path=/dashboard/orders/TG-20261126-UT2Z/confirm/`) | Percobaan mengubah status pesanan tanpa hak. |
| **`00:41:43.319`** | **5** | **DBMS PostgreSQL** *(App blind spot)* | `tg_user@TrailGear_auth` (`PID 10808`) | `LOG: statement: SELECT COUNT(*) ... FROM "catalog_product" ... LIKE UPPER('%'' OR 1=1 --%')` | **Terrekonstruksi lewat DBMS!** Probing SQLi pada `/products/?q=` yang tidak masuk `SecurityEvent` tertangkap utuh di log PostgreSQL 18 ms setelah Tahap 4. |
| `00:41:43.352` | 6a | App DB + `security.log` + DBMS | `m8_attacker` | `LOGOUT` (`user_id=6`) + DBMS `DELETE FROM "django_session" WHERE session_key IN ('3uec8yr9v4vehrt1e9y9ocbsa16m23ir')` (`00:41:43.356`) | Attacker mengakhiri sesi; Django menghapus sesi dari DB. |
| **`00:41:43.359`** | **6b** | **DBMS PostgreSQL** *(App blind spot)* | `tg_user@TrailGear_auth` (`PID 10808`) | `LOG: statement: SELECT "django_session" ... WHERE session_key = '3uec8yr9v4vehrt1e9y9ocbsa16m23ir'` (`HTTP 302 -> /login/`) | **Terrekonstruksi lewat DBMS!** Hanya **3 ms** setelah sesi dihapus, cookie lama dipakai lagi — membuktikan adanya percobaan *session replay* yang ditolak. |

**Kesimpulan Korelasi:** Dengan menggabungkan log Aplikasi (`accounts_securityevent` & `logs/security.log`) dan log DBMS PostgreSQL (`log_statement=all`), **seluruh 6 tahap serangan berantai (100%) berhasil direkonstruksi secara kronologis hingga resolusi milidetik**, termasuk Tahap 5 (SQLi probe) dan Tahap 6b (*session replay*) yang semula merupakan *blind spot* di lapisan aplikasi.

---

## 7. Analisis Keamanan

### 7.1 Jawaban Pertanyaan Teori Modul VIII
1. **Perbedaan General Log dan Audit Log:**
   - *General Log* (padanan PostgreSQL: `log_statement = 'all'`) mencatat seluruh query dan koneksi mentah termasuk `SELECT` rutin. Volume sangat besar dan berdampak pada I/O serta kapasitas disk, sehingga cocok untuk investigasi atau praktikum.
   - *Audit Log* (`accounts_securityevent`, `catalog_inventory_log`, dan PostgreSQL `log_statement = 'mod'/'ddl'`) mencatat peristiwa bernilai keamanan secara selektif, terstruktur, dan berorientasi akuntabilitas (aktor, role, IP, status `BLOCKED`/`FAILURE`, objek terdampak).
2. **Mengapa logging penting dalam keamanan database:** Menyediakan visibilitas aktivitas (*visibility*), akuntabilitas (*non-repudiation*), deteksi dini intrusi, serta bukti forensik digital pasca-insiden.
3. **Bagaimana log membantu mendeteksi serangan:** Melalui korelasi anomali seperti lonjakan `LOGIN_FAILED` / `FATAL: password authentication failed` (brute-force), rangkaian `ACCESS_DENIED` pada endpoint terproteksi (privilege abuse & IDOR), pola payload SQLi di `description`/SQL log, `MAKER_CHECKER_VIOLATION` (*internal fraud*), dan `DROP TABLE` / `ERROR: permission denied` di DBMS.
4. **Risiko jika logging tidak diaktifkan:** Serangan berlangsung tanpa terdeteksi (*silent compromise*), ruang lingkup kebocoran/perubahan data tidak dapat dipastikan, investigasi forensik gagal (*zero evidence*), dan organisasi melanggar standar kepatuhan keamanan informasi.

### 7.2 Evaluasi Keamanan Spesifik TrailGear (Berdasarkan Bukti Aktual)
- **Serangan yang Berhasil Dideteksi:** Brute-force & distributed lockout (`A1`), user enumeration (`A2`), login akun nonaktif/terkunci (`A3`), privilege abuse Customer/Cashier ke Dashboard Kasir/Admin (`B1–B3`), SQLi di login (`C1`), IDOR read/write pesanan & bukti bayar (`D1–D2`), pelanggaran Maker–Checker (`D3`), manipulasi akun/rate-limit oleh Admin (`G2-VERIFY`), kegagalan CSRF (`logs/security.log`), serta di lapisan DBMS: query normal (`F1`), `DROP TABLE`, percobaan `DELETE` tabel audit (`F2`), dan login gagal ke PostgreSQL (`F3`).
- **Serangan yang Belum Terdeteksi di Log Aplikasi (`accounts_securityevent`):** Probing SQLi/XSS pada pencarian publik `/products/?q=` (`C2`, `C3`), *session replay* & *forged session cookie* (`E2`, `E3`), dan redirect `302` ke `/admin/login/` (`D4`). Namun seluruhnya tetap **diblokir/di-escape oleh kontrol keamanan** dan **terlihat di log DBMS** saat `log_statement=all` aktif.
- **Kecukupan Log untuk *Incident Reconstruction*:** **Sangat memadai** setelah Tahap 1 & Tahap 2 diterapkan. Korelasi 6 tahap membuktikan seluruh rantai serangan dapat disusun ulang dengan akurasi milidetik.
- **Temuan Penting Terkait Data Sensitif di Log:**
  - Pada **Log Aplikasi (`accounts_securityevent` & `logs/security.log`)**: **TIDAK ditemukan** kebocoran password plaintext, hash password, token CSRF, maupun `sessionid`.
  - Pada **Log DBMS PostgreSQL (`log_statement = 'all'`)**: Ditemukan fakta forensik nyata (lihat [06_filter_aktivitas_mencurigakan_dbms.txt](file:///d:/Nyoba/praktikum_modul8/06_filter_aktivitas_mencurigakan_dbms.txt) baris `00:41:18.780` dan [05_log_postgresql_dbms.txt](file:///d:/Nyoba/praktikum_modul8/05_log_postgresql_dbms.txt) baris `00:41:43.356`) bahwa ketika `log_statement = 'all'` aktif, query penuh Django ORM ikut menampilkan **hash password PBKDF2** (`"password" = 'pbkdf2_sha256$...'` saat `UPDATE accounts_user`) dan **`session_key`** (`SELECT/DELETE django_session`). Meskipun bukan password plaintext, temuan ini membuktikan bahwa: (1) akses baca terhadap log PostgreSQL harus dibatasi ketat hanya untuk Administrator OS/DBA, dan (2) di lingkungan produksi `log_statement` harus diturunkan dari `'all'` menjadi `'ddl'` atau `'mod'` disertai rotasi serta proteksi ACL berkas log.
- **Kemungkinan Attacker Beraktivitas Tanpa Jejak:** Hanya pada pembacaan halaman publik tanpa autentikasi jika `log_statement` diturunkan dari `'all'` dan tidak ada web-server access log (Nginx/Reverse Proxy) di depan Django.
- **Risiko Jika Event Penting Tidak Tercatat:** Sebelum penutupan Gap G2, akun Admin yang disusupi dapat menaikkan role akun *backdoor* atau menghapus blokir IP brute-force tanpa meninggalkan jejak di `SecurityEvent`; kini risiko tersebut telah dimitigasi dengan `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE`.

---

## 8. Dokumentasi Praktikum (Daftar Bukti yang Telah Dikumpulkan & Panduan Screenshot)

Seluruh bukti teks/output telah tersimpan rapi di folder `d:\Nyoba\praktikum_modul8\`. Jika perlu melampirkan tangkapan layar UI/terminal untuk dokumen cetak, berikut pemetaannya:

| No | Tahap Dokumentasi | Bukti Tersimpan (Sudah Siap) | Tangkapan Layar Tambahan (Opsional di Browser/Terminal) |
| :-: | :--- | :--- | :--- |
| 1 | Kondisi Awal Audit Log (Baseline) | [00_baseline_audit.txt](file:///d:/Nyoba/praktikum_modul8/00_baseline_audit.txt) | Screenshot `/dashboard/admin/security/` |
| 2 | Aktivasi Logging DBMS (G1) | [01_aktivasi_dbms_logging.txt](file:///d:/Nyoba/praktikum_modul8/01_aktivasi_dbms_logging.txt) | Screenshot terminal `psql` menampilkan `log_statement=all`, `log_connections=on` |
| 3 | Aktivitas Attacker (A–F) | [hasil_skenario.json](file:///d:/Nyoba/praktikum_modul8/hasil_skenario.json) & [02_aktivitas_dbms_f1_f3.txt](file:///d:/Nyoba/praktikum_modul8/02_aktivitas_dbms_f1_f3.txt) | Screenshot `psql` error `permission denied` & `FATAL: password authentication failed` |
| 4 | Respons Aplikasi | Tercatat per skenario di [hasil_skenario.json](file:///d:/Nyoba/praktikum_modul8/hasil_skenario.json) | Screenshot halaman `403 Forbidden` saat Customer buka `/dashboard/admin/` & pesan `429 Too Many Requests` |
| 5 | Hasil Audit Log (3 Sumber) | [03_rekap_security_events.txt](file:///d:/Nyoba/praktikum_modul8/03_rekap_security_events.txt) & [05_log_postgresql_dbms.txt](file:///d:/Nyoba/praktikum_modul8/05_log_postgresql_dbms.txt) | Screenshot tabel Log Keamanan di `/dashboard/admin/security/` & Event Viewer (`Application`, source `PostgreSQL`) |
| 6 | Analisis Aktivitas Mencurigakan | [06_filter_aktivitas_mencurigakan_dbms.txt](file:///d:/Nyoba/praktikum_modul8/06_filter_aktivitas_mencurigakan_dbms.txt) | Screenshot hasil `Select-String` PowerShell |
| 7 | Hasil Korelasi Serangan Berantai | [04_korelasi_serangan_berantai.txt](file:///d:/Nyoba/praktikum_modul8/04_korelasi_serangan_berantai.txt) | Screenshot output tabel SQL kronologis IP `198.51.100.77` |

---

## 9. Penilaian Akhir & Kesimpulan

### 9.1 Rekap Hasil Pengujian per Kategori

| Kategori | Total Skenario | Kontrol Keamanan (`PASS`) | Terdeteksi di Log (App / DBMS) | Catatan |
| :--- | :---: | :---: | :---: | :--- |
| A. Recon & Auth Abuse (`A1–A3`) | 3 | **3 / 3** | **3 / 3** (App) | Rate limit 429, lockout 15m, anti-enumeration aktif |
| B. Privilege Abuse (`B1–B3`) | 3 | **3 / 3** | **3 / 3** (App) | 9/9 percobaan direct URL -> `403` + `ACCESS_DENIED` |
| C. Input Attack (`C1–C3`) | 3 | **3 / 3** | **1 / 3 App, 3 / 3 DBMS** | ORM & auto-escape mencegah serangan; `C2`/`C3` terdeteksi di DBMS |
| D. Business Logic Abuse (`D1–D4`) | 4 | **4 / 4** | **4 / 4** (App) | IDOR & Maker–Checker terblokir + tercatat (kecuali redirect `/admin/`) |
| Verifikasi Tahap 2 (`G2-VERIFY`) | 1 | **1 / 1** | **1 / 1** (App) | `ADMIN_USER_UPDATED` & `ADMIN_SECURITY_OVERRIDE` aktif |
| E. Session Abuse (`E1–E3`) | 3 | **3 / 3** | **1 / 3 App, 2 / 3 DBMS** | Kontrol sesi aman (`302`); replay terdeteksi di DBMS (`E2`) |
| F. Suspicious DB Activity (`F1–F3`) | 3 | **3 / 3** | **3 / 3** (DBMS) | `SELECT`, `INSERT`, `DROP`, `permission denied`, `FATAL` tercatat penuh |
| **Total** | **20** | **20 / 20 (100%)** | **15 / 20 App + 100% Lintas-Lapisan** | **DB bersih kembali pasca-uji (`156` produk aman)** |

### 9.2 Pemenuhan Indikator Keberhasilan Modul VIII

| No | Indikator Keberhasilan Modul VIII | Status | Bukti Verifikasi |
| :-: | :--- | :---: | :--- |
| 1 | Mengaktifkan logging pada database | **TERPENUHI** | `log_statement=all`, `log_connections=on`, `log_disconnections=on`, `log_line_prefix='%m [%p] %q%u@%d %r '` aktif; `logging_collector=on` tersimpan di `postgresql.auto.conf` ([01_aktivasi_dbms_logging.txt](file:///d:/Nyoba/praktikum_modul8/01_aktivasi_dbms_logging.txt)). |
| 2 | Menjalankan aktivitas user pada database | **TERPENUHI** | `CREATE`/`INSERT`/`SELECT` (`F1`), `DROP TABLE` dummy & `DELETE` ditolak (`F2`), login gagal (`F3`) ([02_aktivitas_dbms_f1_f3.txt](file:///d:/Nyoba/praktikum_modul8/02_aktivitas_dbms_f1_f3.txt)). |
| 3 | Log berhasil merekam aktivitas | **TERPENUHI** | Terekam lengkap pada `accounts_securityevent`, `logs/security.log`, dan PostgreSQL Audit Log ([03_rekap_security_events.txt](file:///d:/Nyoba/praktikum_modul8/03_rekap_security_events.txt), [05_log_postgresql_dbms.txt](file:///d:/Nyoba/praktikum_modul8/05_log_postgresql_dbms.txt)). |
| 4 | Mampu membaca dan memahami log | **TERPENUHI** | Analisis atribut `timestamp`, `PID`, `user@db`, `IP:port`, `event_type`, `status`, dan `SQL statement`. |
| 5 | Mampu mengidentifikasi aktivitas mencurigakan | **TERPENUHI** | Filter insiden mencurigakan ([06_filter_aktivitas_mencurigakan_dbms.txt](file:///d:/Nyoba/praktikum_modul8/06_filter_aktivitas_mencurigakan_dbms.txt)) & rekonstruksi korelasi 6 tahap ([04_korelasi_serangan_berantai.txt](file:///d:/Nyoba/praktikum_modul8/04_korelasi_serangan_berantai.txt)). |
| 6 | Menyimpulkan fungsi audit trail | **TERPENUHI** | Analisis Bagian 7 & kesimpulan akhir terverifikasi data aktual. |

### 9.3 Rekomendasi Tindak Lanjut Pasca-Praktikum
1. **Switch Output Log PostgreSQL ke File (Opsional, Memerlukan PowerShell Administrator):** Jalankan `Restart-Service postgresql-x64-18` agar `logging_collector = on` mulai menulis ke file `D:\Apps\PostgreSQL18\data\log\postgresql-YYYY-MM-DD.log` (selain Windows Event Log).
2. **Penyesuaian Produksi Pasca-Penilaian:** Setelah penilaian praktikum selesai, ubah `log_statement` dari `'all'` menjadi `'mod'` (atau `'ddl'`) via `ALTER SYSTEM SET log_statement = 'mod'; SELECT pg_reload_conf();` untuk mencegah pertumbuhan log berlebih sekaligus menghindari pencatatan `SELECT django_session` berulang.
3. **Penguatan Lanjutan (Opsional):** Aktifkan web server access log (Nginx/Caddy) di depan Django untuk menangkap *reconnaissance* pada endpoint publik (`C2`/`C3`) dan pertimbangkan *middleware* deteksi *session replay* bila diperlukan alert langsung di Dashboard Keamanan Admin.
