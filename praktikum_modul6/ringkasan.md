# Ringkasan Praktikum Modul VI — Konfigurasi Password Policy & Authentication (PostgreSQL Lokal)

## Parameter Praktikum
- **DBMS**: `PostgreSQL 18.6 on x86_64-windows, compiled by msvc-19.44.35229, 64-bit`
- **Host / Port**: `127.0.0.1:5432`
- **User Admin**: `postgres` (`rolsuper = t`)
- **Database Uji**: `kbd_auth`
- **Role Uji**: `uji_lemah`, `uji_kuat`
- **Folder Bukti**: `./praktikum_modul6/`

---

## Tabel Hasil Pelaksanaan per Langkah

| No. Langkah (Padanan Modul) | Perintah yang Dijalankan | Output Singkat (Nyata) | Status | File Bukti |
| :--- | :--- | :--- | :---: | :--- |
| **0** (Pemeriksaan Awal) | `SELECT version();`<br>`SELECT rolname, rolsuper FROM pg_roles WHERE rolname = current_user;`<br>`SHOW config_file;`<br>`SHOW hba_file;` | `PostgreSQL 18.6 on x86_64-windows`<br>`postgres \| t`<br>`D:/Apps/PostgreSQL18/data/postgresql.conf`<br>`D:/Apps/PostgreSQL18/data/pg_hba.conf` | **Berhasil** | [`00_cek_awal.txt`](./00_cek_awal.txt) |
| **1a** (5.2 / 5.3 — Cek Modul Awal) | `SHOW shared_preload_libraries;`<br>`SELECT name FROM pg_available_extensions WHERE name IN ('passwordcheck', 'auth_delay');` | `shared_preload_libraries`: *(kosong)*<br>`pg_available_extensions`: `(0 rows)` *(karena `passwordcheck.dll` & `auth_delay.dll` adalah shared library hook di folder `lib/`, bukan SQL extension)* | **Berhasil** | [`01_policy_dbms.txt`](./01_policy_dbms.txt) |
| **1b** (5.2 / 5.3 — Aktifkan `passwordcheck`) | Set `shared_preload_libraries = 'passwordcheck'` di `postgresql.conf`, restart PostgreSQL, lalu:<br>`SHOW shared_preload_libraries;` | `shared_preload_libraries = passwordcheck` `(1 row)` | **Berhasil** | [`01_policy_dbms.txt`](./01_policy_dbms.txt) |
| **2** (5.5 — Uji Role Password Lemah) | `DROP ROLE IF EXISTS uji_lemah;`<br>`CREATE ROLE uji_lemah LOGIN PASSWORD '<REDACTED_WEAK_PASSWORD>';` | `ERROR: password is too short`<br>`DETAIL: password must be at least "passwordcheck.min_password_length" (8) bytes long` | **Gagal (Sesuai Harapan / Ditolak Policy)** | [`02_role_lemah.txt`](./02_role_lemah.txt) |
| **3a** (5.6 — Buat Role Password Kuat) | `DROP ROLE IF EXISTS uji_kuat;`<br>`CREATE ROLE uji_kuat LOGIN PASSWORD '<REDACTED_STRONG_PASSWORD>';` | `DROP ROLE`<br>`CREATE ROLE` | **Berhasil** | [`03_role_kuat.txt`](./03_role_kuat.txt) |
| **3b** (5.6 — Uji Login `uji_kuat` Benar) | `psql -h 127.0.0.1 -U uji_kuat -d kbd_auth -c "SELECT current_user;"` | `current_user: uji_kuat (1 row)` | **Berhasil** | [`03_role_kuat.txt`](./03_role_kuat.txt) |
| **3c** (5.6 — Uji Login `uji_kuat` Password Salah) | `psql -h 127.0.0.1 -U uji_kuat -d kbd_auth` *(dengan password salah)* | `psql: error: connection to server at "127.0.0.1", port 5432 failed: FATAL: password gagal diotentikasi untuk pengguna « uji_kuat »` | **Gagal (Sesuai Harapan / Ditolak Autentikasi)** | [`03_role_kuat.txt`](./03_role_kuat.txt) |
| **4a** (5.7 — Set Masa Berlaku Kedaluwarsa) | `ALTER ROLE uji_kuat VALID UNTIL '2026-01-01';`<br>Lalu uji login dengan password benar | `ALTER ROLE`<br>Saat login: `FATAL: password gagal diotentikasi untuk pengguna « uji_kuat »` *(ditolak karena telah melewati `VALID UNTIL`)* | **Gagal Login (Sesuai Harapan / Akun Expired)** | [`04_valid_until.txt`](./04_valid_until.txt) |
| **4b** (5.7 — Pulihkan Masa Berlaku) | `ALTER ROLE uji_kuat VALID UNTIL 'infinity';`<br>`psql -h 127.0.0.1 -U uji_kuat -d kbd_auth -c "SELECT current_user;"` | `ALTER ROLE`<br>`current_user: uji_kuat (1 row)` | **Berhasil** | [`04_valid_until.txt`](./04_valid_until.txt) |
| **5** (5.8 — Uji Lock Akun di DBMS) | `ALTER ROLE uji_kuat FAILED_LOGIN_ATTEMPTS 3;` | `ERROR: opsi role « failed_login_attempts » tidak dikenali`<br>`LINE 1: ALTER ROLE uji_kuat FAILED_LOGIN_ATTEMPTS 3;` | **Tidak Didukung** *(Diimplementasikan di Aplikasi)* | [`05_failed_login_attempts.txt`](./05_failed_login_attempts.txt) |

---

## Catatan Penjelasan Teknis Berdasarkan Output Nyata

1. **`pg_available_extensions` menghasilkan `(0 rows)` pada Langkah 1:**
   Di PostgreSQL, `passwordcheck` dan `auth_delay` adalah modul C hook berbentuk *shared library* (`D:\Apps\PostgreSQL18\lib\passwordcheck.dll` dan `auth_delay.dll`) yang dimuat saat server start melalui `shared_preload_libraries`, bukan ekstensi SQL (`CREATE EXTENSION`) yang memiliki file `.control`.
2. **Pesan Penolakan Saat `VALID UNTIL` Habis (Langkah 4):**
   PostgreSQL mengembalikan pesan generik `FATAL: password gagal diotentikasi untuk pengguna « uji_kuat »` walaupun password yang dikirimkan benar. Ini adalah perilaku keamanan standar PostgreSQL agar penyerang dari luar tidak dapat membedakan apakah kegagalan disebabkan oleh password salah atau masa berlaku akun yang sudah habis.
3. **Ketidaktersediaan `FAILED_LOGIN_ATTEMPTS` Bawaan (Langkah 5):**
   Klausa `FAILED_LOGIN_ATTEMPTS` pada `ALTER ROLE` tidak dikenal oleh parser SQL PostgreSQL (`ERROR: opsi role « failed_login_attempts » tidak dikenali`). Oleh sebab itu, mekanisme *Account Lockout* pada proyek TrailGear diimplementasikan di lapisan aplikasi Django (`User.failed_login_attempts` dan `User.locked_until`).

---

## Daftar Screenshot yang Perlu Anda Ambil (Sesuai Urutan Langkah)

1. **Screenshot 1 (Langkah 0 — Pemeriksaan Awal):**
   Tampilkan output query `SELECT version();`, `SELECT rolname, rolsuper FROM pg_roles WHERE rolname = current_user;`, `SHOW config_file;`, dan `SHOW hba_file;` (atau isi file [`00_cek_awal.txt`](./00_cek_awal.txt)).
2. **Screenshot 2 (Langkah 1 — Sebelum & Sesudah Aktivasi `passwordcheck`):**
   * Tampilkan baris `shared_preload_libraries = 'passwordcheck'` pada file `postgresql.conf`.
   * Tampilkan hasil `SHOW shared_preload_libraries;` sebelum (kosong) dan sesudah restart (`passwordcheck`) seperti pada [`01_policy_dbms.txt`](./01_policy_dbms.txt).
3. **Screenshot 3 (Langkah 2 — Pembuatan Role Password Lemah Ditolak):**
   Tampilkan eksekusi `CREATE ROLE uji_lemah LOGIN PASSWORD '...';` yang ditolak dengan pesan `ERROR: password is too short` / `DETAIL: password must be at least "passwordcheck.min_password_length" (8) bytes long` ([`02_role_lemah.txt`](./02_role_lemah.txt)).
4. **Screenshot 4 (Langkah 3 — Pembuatan Role Kuat & Uji Login Benar vs Salah):**
   * Eksekusi `CREATE ROLE uji_kuat` berhasil (`CREATE ROLE`).
   * Login `psql -h 127.0.0.1 -U uji_kuat -d kbd_auth -c "SELECT current_user;"` dengan password benar menampilkan `uji_kuat`.
   * Login dengan password salah menampilkan `FATAL: password gagal diotentikasi untuk pengguna « uji_kuat »` ([`03_role_kuat.txt`](./03_role_kuat.txt)).
5. **Screenshot 5 (Langkah 4 — Uji Masa Berlaku Akun `VALID UNTIL`):**
   * Eksekusi `ALTER ROLE uji_kuat VALID UNTIL '2026-01-01';` diikuti percobaan login dengan password benar yang ditolak (`FATAL: password gagal diotentikasi...`).
   * Eksekusi `ALTER ROLE uji_kuat VALID UNTIL 'infinity';` diikuti percobaan login kembali yang berhasil menampilkan `uji_kuat` ([`04_valid_until.txt`](./04_valid_until.txt)).
6. **Screenshot 6 (Langkah 5 — Bukti `FAILED_LOGIN_ATTEMPTS` Tidak Didukung di PostgreSQL):**
   Tampilkan eksekusi `ALTER ROLE uji_kuat FAILED_LOGIN_ATTEMPTS 3;` yang menghasilkan `ERROR: opsi role « failed_login_attempts » tidak dikenali` ([`05_failed_login_attempts.txt`](./05_failed_login_attempts.txt)).
