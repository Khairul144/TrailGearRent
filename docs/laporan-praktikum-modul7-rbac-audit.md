# LAPORAN PRAKTIKUM KEAMANAN — Skema Privilege Minimum, Maker-Checker, Audit Log & User Access Review

**Sistem:** TrailGear Rent (`TrailGear_auth` — PostgreSQL 18.6 & Django 6.1)  
**Tanggal Pelaksanaan:** 16 November 2026  
**Lokasi Bukti Praktikum:** [`praktikum_modul7/`](../praktikum_modul7/ringkasan.md)

---

## 1. Perancangan Skema Privilege Minimum (*Principle of Least Privilege*) pada DBMS Lab

### 1.1 Hardening Schema Default
Secara bawaan, role `PUBLIC` memiliki akses pada schema `public`. Langkah pertama adalah mencabut hak `CREATE` dari `PUBLIC` agar role tanpa otorisasi tidak dapat membuat tabel/fungsi liar:
```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO PUBLIC;
```

### 1.2 Matriks Role & Privilege Minimum di PostgreSQL (`TrailGear_auth`)
Dibuat 3 *group role* (`NOLOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`) dengan pembagian hak akses minimum hingga ke level kolom (*column-level privilege*):

| Role DBMS | Representasi Aktor | Hak Akses Diizinkan (`GRANT`) | Hak Akses Dibatasi / Ditolak (`REVOKE`) |
| :--- | :--- | :--- | :--- |
| **`role_customer_db`** | Pelanggan (*Maker*) | `SELECT` pada `catalog_category`, `catalog_product`;<br>`SELECT, INSERT` pada `rentals_cart`, `rentals_cart_item`, `rentals_rental_order`, `rentals_rental_order_item` | Dilarang `UPDATE` status pesanan, dilarang `DELETE` tabel apa pun, dilarang mengakses `accounts_securityevent` dan `accounts_user`. |
| **`role_kasir_db`** | Staf Kasir (*Checker*) | `SELECT` katalog & profil dasar pelanggan (`id, username, first_name, last_name, email, phone_number, is_active` pada `accounts_user`);<br>`UPDATE (available_stock, updated_at)` pada `catalog_product`;<br>`SELECT, UPDATE (status, stock_deducted, actual_return_date, overdue_days, overdue_fine, damage_fine, total_fine, fine_payment_status, return_notes, returned_by_staff_id, updated_at)` pada `rentals_rental_order`;<br>`SELECT, UPDATE (condition_at_return, item_damage_fee)` pada `rentals_rental_order_item`;<br>`SELECT, INSERT` pada `catalog_inventory_log` & `accounts_securityevent` | Dilarang mengubah harga sewa atau nama produk (`price_per_day`, `name`), dilarang membaca kolom `password` pada `accounts_user`, dilarang `DELETE` pesanan maupun log audit. |
| **`role_auditor_db`** | Auditor Internal (*Read-Only*) | `SELECT` pada `accounts_securityevent`, `catalog_inventory_log`, `rentals_rental_order`, `rentals_rental_order_item`, `catalog_product`, `catalog_category`, `auth_group`, `accounts_user_groups`;<br>`SELECT` kolom non-rahasia pada `accounts_user` (**tanpa kolom `password`**) | Dilarang melakukan `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` di seluruh tabel, serta dilarang membaca hash `password`. |

### 1.3 Hasil Pengujian Pelanggaran Least Privilege ([`01_least_privilege_dbms.txt`](../praktikum_modul7/01_least_privilege_dbms.txt))
1. **`role_customer_db` membaca katalog vs membaca log keamanan / menghapus produk:**
   - `SELECT count(*) FROM catalog_product;` $\rightarrow$ **Berhasil (`156`)**
   - `SELECT count(*) FROM accounts_securityevent;` $\rightarrow$ **`ERROR: permission denied for table accounts_securityevent`**
   - `DELETE FROM catalog_product WHERE id = 1;` $\rightarrow$ **`ERROR: permission denied for table catalog_product`**
2. **`role_kasir_db` mencoba memanipulasi harga sewa atau menghapus jejak audit:**
   - `UPDATE catalog_product SET price_per_day = 1000 WHERE id = 1;` $\rightarrow$ **`ERROR: permission denied for table catalog_product`**
   - `DELETE FROM accounts_securityevent;` $\rightarrow$ **`ERROR: permission denied for table accounts_securityevent`**
3. **`role_auditor_db` membaca profil akun vs membaca hash password:**
   - `SELECT id, username, is_active, is_staff FROM accounts_user;` $\rightarrow$ **Berhasil (`2 rows: admin1, kasir1`)**
   - `SELECT username, password FROM accounts_user LIMIT 1;` $\rightarrow$ **`ERROR: permission denied for table accounts_user`**

---

## 2. Simulasi Pemisahan Role *Maker–Checker* & Pengujian Pelanggarannya

Prinsip *Separation of Duties (Maker–Checker)* diterapkan secara berlapis (*Defense-in-Depth*) baik di **Lapisan Aplikasi Django** ([rentals/services.py](../rentals/services.py), [rentals/views.py](../rentals/views.py)) maupun di **Lapisan DBMS PostgreSQL** ([`02_maker_checker_dbms.txt`](../praktikum_modul7/02_maker_checker_dbms.txt)).

### 2.1 Aturan Maker–Checker yang Diterapkan
1. **Pemisahan Role Eksternal (`Customer` vs `Cashier`/`Admin`):**
   - **Maker:** `Customer` membuat pesanan (`MENUNGGU_PEMBAYARAN`) dan mengunggah bukti pembayaran.
   - **Checker:** Hanya `Cashier` atau `Admin` yang dapat memverifikasi pembayaran (`DIKONFIRMASI`), menyerahkan barang (`DIAMBIL`), memeriksa pengembalian (`KEMBALI`), dan melunasi denda (`LUNAS`).
2. **Pencegahan *Self-Approval* (`Maker != Checker`):**
   - Di `rentals/services.py` (`set_order_status`, `complete_return`, `settle_fine`): apabila staf membuat pesanan untuk dirinya sendiri (`order.user_id == actor.pk`), sistem melempar `MakerCheckerViolationError` dan mencatat event audit `MAKER_CHECKER_VIOLATION` (`STATUS_BLOCKED`).
   - Di PostgreSQL (`trg_enforce_maker_checker_order` pada `rentals_rental_order`): trigger menolak transaksi apabila `NEW.returned_by_staff_id = NEW.user_id` dengan kode error `42501`.

### 2.2 Hasil Pengujian Pelanggaran Maker–Checker
| Skenario Uji | Level Uji | Aksi yang Diuji | Hasil Aktual | Status |
| :--- | :---: | :--- | :--- | :---: |
| **Pelanggaran 1: Role Maker mencoba Approve** | DBMS (`psql`) | `SET ROLE role_customer_db;` lalu `UPDATE rentals_rental_order SET status='DIKONFIRMASI'` | `ERROR: permission denied for table rentals_rental_order` | **PASS (Ditolak)** |
| **Pelanggaran 2: Self-Approval di DBMS** | DBMS (`psql`) | `SET ROLE role_kasir_db;` lalu `UPDATE rentals_rental_order SET status='KEMBALI', returned_by_staff_id = user_id` | `ERROR: Maker-Checker Violation: Pembuat pesanan (user_id=3) tidak diizinkan memverifikasi/menyelesaikan pesanannya sendiri (returned_by_staff_id=3).` | **PASS (Ditolak Trigger)** |
| **Alur Valid di DBMS (`Maker != Checker`)** | DBMS (`psql`) | `Maker = admin1 (id=3)`, `Checker = kasir1 (id=4)` via `SET ROLE role_kasir_db` | `UPDATE 1` (`status = DIKONFIRMASI, maker_id = 3, checker_id = 4`) | **PASS (Berhasil)** |
| **Pelanggaran 3: Customer akses endpoint Kasir** | Aplikasi Django | `POST /dashboard/orders/<code>/action/confirm/` oleh `Customer` | `HTTP 403 Forbidden` + `SecurityEvent.ACCESS_DENIED` | **PASS (Ditolak)** |
| **Pelanggaran 4: Kasir mengonfirmasi pesanannya sendiri** | Aplikasi Django | `test_maker_cannot_confirm_own_order_even_if_staff` | Status tetap `MENUNGGU_PEMBAYARAN` + tercatat `MAKER_CHECKER_VIOLATION (BLOCKED)` | **PASS (Ditolak)** |
| **Pelanggaran 5: Kasir memproses return / denda pesanannya sendiri** | Aplikasi Django | `test_maker_cannot_complete_return_on_own_order` & `test_maker_cannot_settle_fine_on_own_order` | Ditolak + tercatat `MAKER_CHECKER_VIOLATION (BLOCKED)` | **PASS (Ditolak)** |
| **Alur Valid di Aplikasi (`Maker != Checker`)** | Aplikasi Django | `test_different_checker_can_confirm_order_and_logs_approval` | Status berubah ke `DIKONFIRMASI` + tercatat `ORDER_APPROVED (SUCCESS)` | **PASS (Berhasil)** |

---

## 3. Aktivasi Audit Log (DBMS & Aplikasi)

### 3.1 Aktivasi Audit Log PostgreSQL ([`03_audit_log_dbms.txt`](../praktikum_modul7/03_audit_log_dbms.txt))
Konfigurasi audit pada PostgreSQL 18 diaktifkan melalui `ALTER SYSTEM` dan dimuat ulang tanpa memutus layanan menggunakan `SELECT pg_reload_conf();`:

| Parameter PostgreSQL | Sebelum | Sesudah | Fungsi Audit |
| :--- | :---: | :---: | :--- |
| `logging_collector` | `on` | `on` | Menangkap dan menulis aliran log ke `D:/Apps/PostgreSQL18/data/log/` |
| `log_statement` | `none` | **`mod`** | Mencatat seluruh pernyataan DDL (`CREATE`, `ALTER`, `DROP`, `GRANT`, `REVOKE`) dan DML (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`) |
| `log_connections` | `off` | **`on`** | Mencatat setiap koneksi masuk beserta host/port |
| `log_disconnections` | `off` | **`on`** | Mencatat setiap pemutusan sesi beserta durasi sesi |

Cuplikan nyata dari file log PostgreSQL (`postgresql-2026-11-16_000000.log`):
```text
2026-11-16 11:07:49 +07 LOG:  perintah: UPDATE rentals_rental_order SET status = 'DIKONFIRMASI' WHERE order_code = 'TG-20261116-MC01';
2026-11-16 11:07:49 +07 ERROR:  permission denied for table rentals_rental_order
2026-11-16 11:07:49 +07 LOG:  perintah: UPDATE rentals_rental_order SET status = 'KEMBALI', returned_by_staff_id = user_id WHERE order_code = 'TG-20261116-MC01';
2026-11-16 11:07:49 +07 ERROR:  Maker-Checker Violation: Pembuat pesanan (user_id=3) tidak diizinkan memverifikasi/menyelesaikan pesanannya sendiri (returned_by_staff_id=3).
2026-11-16 11:07:49 +07 LOG:  pemutusan koneksi: sesi waktu: 0:00:00.061 pengguna=postgres database=TrailGear_auth host=127.0.0.1
```

### 3.2 Audit Log Aplikasi Django
Selain log DBMS, aplikasi mencatat peristiwa keamanan secara terstruktur di tabel `accounts_securityevent` dan `logs/security.log`, termasuk jenis peristiwa baru:
- `ORDER_APPROVED` (`SUCCESS`): Mencatat ID Maker, ID Checker, kode pesanan, dan status tujuan.
- `MAKER_CHECKER_VIOLATION` (`BLOCKED`): Mencatat percobaan *self-approval* oleh pembuat pesanan.

---

## 4. Laporan *User Access Review* (UAR) Sederhana

Laporan UAR tersedia secara *real-time* di halaman web **`/dashboard/admin/security/`** ([security.html](../templates/accounts/admin/security.html)) serta dieksekusi langsung di DBMS ([`04_user_access_review.txt`](../praktikum_modul7/04_user_access_review.txt)).

### 4.1 Tabel Evaluasi UAR — Role DBMS PostgreSQL (`pg_roles`)
| Role DBMS | Superuser | CreateRole | CreateDB | Can Login (Sebelum) | Valid Until | Temuan Audit UAR | Tindakan Remediasi & Status Akhir |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| `postgres` | Ya | Ya | Ya | Ya | $\infty$ | Superuser utama DBMS | **MAINTAIN** (Hanya untuk administrasi DBA) |
| `tg_user` | Tidak | Tidak | Ya* | Ya | $\infty$ | Akun koneksi aplikasi utama (`createdb` dibutuhkan untuk pembuatan test DB `test_TrailGear_auth`) | **MAINTAIN** (Bukan superuser, tidak bisa membuat role) |
| `role_customer_db` | Tidak | Tidak | Tidak | Tidak | $\infty$ | Group Role Least Privilege Pelanggan | **MAINTAIN** (Sesuai skema privilege minimum) |
| `role_kasir_db` | Tidak | Tidak | Tidak | Tidak | $\infty$ | Group Role Least Privilege Kasir | **MAINTAIN** (Sesuai skema privilege minimum) |
| `role_auditor_db` | Tidak | Tidak | Tidak | Tidak | $\infty$ | Group Role Least Privilege Auditor | **MAINTAIN** (Read-only, tanpa akses kolom `password`) |
| `uji_kuat` | Tidak | Tidak | Tidak | **Ya $\rightarrow$ Tidak** | `2026-01-01` | **TEMUAN:** Akun uji dari Modul VI sudah kedaluwarsa (`valid_until < NOW()`) namun atribut `rolcanlogin` masih `true` | **REMEDIATED:** Dicabut hak loginnya dengan `ALTER ROLE uji_kuat NOLOGIN;` (`can_login = false`) |

### 4.2 Tabel Evaluasi UAR — Akun Aplikasi TrailGear (`accounts_user`)
| ID | Username | Email | Role (Group) | Aktif | `is_staff` | `is_superuser` | Keputusan UAR |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 3 | `admin1` | `admin1@trailgear.local` | `Admin` | Ya | Ya | Tidak | **MAINTAIN** (Sesuai Role Admin) |
| 4 | `kasir1` | `kasir1@trailgear.local` | `Cashier` | Ya | Tidak | Tidak | **MAINTAIN** (Sesuai Least Privilege Kasir) |
