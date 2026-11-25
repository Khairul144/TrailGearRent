# Ringkasan Bukti Praktikum Modul VIII — Audit Trail & Logging Database (TrailGear)

**Tanggal Eksekusi:** 26 November 2026  
**Stack:** Django 6.1 + PostgreSQL 18.6 (`TrailGear_auth`, `127.0.0.1:5432`) pada Windows 11  
**Laporan Lengkap:** [laporan-praktikum-modul8-audit-trail.md](file:///d:/Nyoba/docs/laporan-praktikum-modul8-audit-trail.md)

## Status Akhir Eksekusi
- **Tahap 1 (PostgreSQL 18 Audit Logging — Gap G1):** `log_statement=all`, `log_connections=on`, `log_disconnections=on`, `log_line_prefix='%m [%p] %q%u@%d %r '` **aktif langsung** via `ALTER SYSTEM` + `pg_reload_conf()`. Parameter `logging_collector='on'` telah ditulis ke `postgresql.auto.conf` (tinggal menjalankan `Restart-Service postgresql-x64-18` di PowerShell Administrator untuk memindahkan output log dari Windows Application Event Log ke file `D:\Apps\PostgreSQL18\data\log\postgresql-YYYY-MM-DD.log`).
- **Tahap 2 (Penguatan Audit Trail Aplikasi — Gap G2 & G6):**
  - Menambahkan `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE` pada [accounts/models.py](file:///d:/Nyoba/accounts/models.py#L185-L209) + migrasi [0011_alter_securityevent_event_type.py](file:///d:/Nyoba/accounts/migrations/0011_alter_securityevent_event_type.py).
  - Menambahkan `log_event()` pada aksi sensitif Admin (`admin_user_manage` unlock & ubah role/status, `admin_user_toggle`, `admin_reset_ratelimit`) di [accounts/views.py](file:///d:/Nyoba/accounts/views.py#L546-L695).
  - Mengarahkan logger `django.request` dan `django.security.csrf` ke `security_file` (`logs/security.log`) di [config/settings.py](file:///d:/Nyoba/config/settings.py#L289-L299).
- **Tahap 3 (Simulasi Attacker A–F + G2-VERIFY + Serangan Berantai):** **20 / 20 skenario PASS** (`A1–A3`, `B1–B3`, `C1–C3`, `D1–D4`, `G2-VERIFY`, `E1–E3`, `F1–F3`), seluruh data uji dibersihkan kembali.
- **Tahap 4 (Verifikasi Unit Test & Kebersihan DB):**
  - `manage.py check`: `System check identified no issues (0 silenced).`
  - `manage.py test accounts.tests.AdminUserManageAndRateLimitResetTests accounts.tests.UserAccessReviewTests -v 2`: **7 / 7 test OK**.
  - Kondisi DB pasca-cleanup: `users = 2 (admin1, kasir1)`, `products = 156`, `orders = 0`, `security_events = 0`, `inventory_logs = 167`, `uji_audit_tmp = 0`.

## Indeks Berkas Bukti (`d:\Nyoba\praktikum_modul8\`)

| No | Berkas Bukti | Isi / Kegunaan Dokumentasi |
| :-: | :--- | :--- |
| 1 | [00_baseline_audit.txt](file:///d:/Nyoba/praktikum_modul8/00_baseline_audit.txt) | Kondisi awal parameter PostgreSQL (`logging_collector=off`, `log_statement=none`) & jumlah baris tabel audit. |
| 2 | [01_aktivasi_dbms_logging.txt](file:///d:/Nyoba/praktikum_modul8/01_aktivasi_dbms_logging.txt) | Output `ALTER SYSTEM SET ...`, `pg_reload_conf()`, dan verifikasi parameter aktif PostgreSQL 18. |
| 3 | [02_aktivitas_dbms_f1_f3.txt](file:///d:/Nyoba/praktikum_modul8/02_aktivitas_dbms_f1_f3.txt) | Output `psql` untuk Skenario F1 (`CREATE`/`INSERT`/`SELECT` tabel dummy), F2 (`DROP TABLE uji_audit_tmp` & `DELETE accounts_securityevent` ditolak `permission denied`), dan F3 (login gagal `normal_user`). |
| 4 | [03_rekap_security_events.txt](file:///d:/Nyoba/praktikum_modul8/03_rekap_security_events.txt) | Rekap agregasi `accounts_securityevent` (50 event dari 10 tipe) & 35 baris terakhir `logs/security.log`. |
| 5 | [04_korelasi_serangan_berantai.txt](file:///d:/Nyoba/praktikum_modul8/04_korelasi_serangan_berantai.txt) | Output query SQL rekonstruksi kronologis serangan berantai 6 tahap dari IP `198.51.100.77`. |
| 6 | [05_log_postgresql_dbms.txt](file:///d:/Nyoba/praktikum_modul8/05_log_postgresql_dbms.txt) | Cuplikan log audit PostgreSQL 18 (koneksi TLSv1.3, statement Stage 5 SQLi probe & Stage 6b session replay, disconnection). |
| 7 | [06_filter_aktivitas_mencurigakan_dbms.txt](file:///d:/Nyoba/praktikum_modul8/06_filter_aktivitas_mencurigakan_dbms.txt) | Hasil filter aktivitas mencurigakan di PostgreSQL Event Log (`DROP TABLE`, `ERROR: permission denied`, `FATAL: password authentication failed`, SQLi/XSS) & `logs/security.log` (`BLOCKED`, `FAILURE`, `django.security.csrf`, `ADMIN_*`). |
| 8 | [hasil_skenario.json](file:///d:/Nyoba/praktikum_modul8/hasil_skenario.json) | Rekap terstruktur JSON dari seluruh 20 skenario pengujian (status HTTP/DBMS, detail respons, event yang tercatat, dan PASS/FAIL). |
