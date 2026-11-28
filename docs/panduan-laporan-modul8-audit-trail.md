# Panduan Eksekusi Mandiri & Draf Laporan Praktikum Modul VIII: Konfigurasi Audit Trail dan Logging Database — TrailGear (Django + PostgreSQL 18)

> **Cara Menggunakan Dokumen Ini:**
> - Setiap langkah disusun persis mengikuti alur laporan praktikum (*Tujuan*, *Penjelasan*, *Perintah / Aksi Browser*, *Keterangan*, *Hasil yang diharapkan*, dan slot **`[Tempel Screenshot: Gambar X]`**).
> - Seluruh perintah terminal ditulis untuk **Windows PowerShell** pada direktori proyek `d:\Nyoba` dengan PostgreSQL 18 (`D:\Apps\PostgreSQL18`) dan virtual environment Python `.\.venv\Scripts\python.exe`.
> - Seluruh pengujian menggunakan **akun uji sementara** (`m8_attacker`, `m8_victim`, `m8_disabled`) dan **tabel dummy terisolasi** (`uji_audit_tmp`), lalu dibersihkan kembali pada Langkah 11.7 agar data produksi (`156` produk, `admin1`, `kasir1`) tetap aman.

---

## AUDIT KONDISI AWAL (*BASELINE ASSESSMENT*) & GAP ANALYSIS

### 1. Kondisi Audit Trail TrailGear Sebelum Aktivasi DBMS Logging

Proyek **TrailGear** (`Django 6.1` + `PostgreSQL 18.6`) memiliki **3 lapisan pencatatan**, dengan kondisi baseline sebagai berikut:

1. **Lapisan 1 — Application Security Event Logging (Sudah Aktif & Matang):**
   - Mekanisme *dual-sink* melalui fungsi `log_event()` di `accounts/security.py` yang menulis secara bersamaan ke tabel PostgreSQL **`accounts_securityevent`** dan berkas log rotasi **`logs/security.log`** (`RotatingFileHandler`, maks 5 MB, 3 file backup, UTF-8).
   - Mencatat atribut `timestamp`, `event_type`, `status` (`SUCCESS` / `FAILURE` / `BLOCKED`), `user_id`, `ip_address`, `user_agent`, dan `description` (newline dibersihkan untuk mencegah *log injection*).
   - Halaman monitoring admin tersedia di `/dashboard/admin/security/` (filter status/event/pencarian, status parameter audit DBMS, kontrol buka blokir IP/akun, ekspor CSV, dan laporan *User Access Review*). Di Django Admin, `SecurityEventAdmin` bersifat *append-only/read-only*.
2. **Lapisan 2 — Business Inventory & Django Admin Audit (Sudah Aktif):**
   - Tabel **`catalog_inventory_log`** mencatat mutasi stok (`INITIAL_SEED`, `RESTOCK`, `RENTED`, `RETURNED`, `DAMAGED`, `ADJUSTMENT`) beserta `changed_by`, `stock_before`, `stock_after`, dan `notes` (`167` baris baseline).
   - Tabel **`django_admin_log`** mencatat operasi melalui panel `/admin/`.
3. **Lapisan 3 — DBMS Audit Logging PostgreSQL 18 (`TrailGear_auth`) — Awalnya Nonaktif:**
   - Pada kondisi default instalasi, `logging_collector = off`, `log_statement = none`, `log_connections = off`, `log_disconnections = off`, dan `log_line_prefix = '%m [%p] '` (belum mencantumkan user DBMS `%u`, nama DB `%d`, dan IP client `%r`).

### 2. Gap Analysis

| Kategori | Komponen / Temuan | Tindak Lanjut pada Praktikum |
| :--- | :--- | :--- |
| **Sudah Tersedia** | Audit dual-sink `accounts_securityevent` + `logs/security.log`, `catalog_inventory_log`, dashboard `/dashboard/admin/security/`, proteksi ORM (SQLi), auto-escaping (XSS), CSRF, RBAC, IDOR, Maker–Checker. | Digunakan dan diuji langsung pada Langkah 5–11. |
| **Gap G1 (Kritis — Wajib Modul VIII)** | Logging DBMS PostgreSQL 18 awalnya nonaktif (`logging_collector=off`, `log_statement=none`, `log_connections=off`). | Diaktifkan pada **Langkah 2** via `ALTER SYSTEM` + restart `pg_ctl.exe`. |
| **Gap G2 (Audit Admin)** | Aksi sensitif Admin (`admin_user_manage` unlock & ubah role/status, `admin_user_toggle`, `admin_reset_ratelimit`) sebelumnya belum tercatat di `SecurityEvent`. | Ditutup dengan event `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE` (diverifikasi di **Langkah 3 & 8.5**). |
| **Gap G6 (Persistensi CSRF)** | Logger `django.security.csrf` dan `django.request` sebelumnya belum diarahkan ke `security_file`. | Diarahkan ke `logs/security.log` di `config/settings.py` (diverifikasi di **Langkah 3.3**). |
| **Gap G4 & G5 (Blind Spot Uji Jujur)** | Probing SQLi/XSS pada pencarian katalog publik (`/products/?q=`) dan *session replay* dengan cookie lama (`E2`/`E3`) tetap ditahan/di-escape, namun tidak menulis baris ke `accounts_securityevent`. | Diuji secara jujur pada **Langkah 7, 9, dan 11** untuk membuktikan bagaimana log DBMS (`log_statement=all`) menutup *blind spot* lapisan aplikasi. |
| **Tidak Relevan (MySQL vs PostgreSQL)** | `general_log`, `INSTALL PLUGIN audit_log SONAME 'audit_log.so'`, `/var/lib/mysql/*.log`. | Disesuaikan dengan padanan resmi PostgreSQL 18 (`logging_collector`, `log_statement`, `log_connections`, `log_line_prefix`, `pg_current_logfile()`, dan PowerShell `Get-Content`/`Select-String`). |

---

## BAB III LANGKAH PRAKTIKUM DAN HASIL

### Langkah 1. Persiapan Lingkungan & Audit Kondisi Awal (*Baseline*)

**Tujuan:** Memeriksa status awal parameter logging PostgreSQL 18, kondisi awal tabel audit aplikasi, serta memastikan server Django TrailGear berjalan normal sebelum konfigurasi diubah.

**Penjelasan:** Sebelum mengaktifkan audit logging, kondisi awal (*baseline*) perlu didokumentasikan agar perubahan sebelum dan sesudah konfigurasi dapat dibuktikan secara objektif.

#### 1.1 Masuk ke folder proyek dan jalankan pemeriksaan kesehatan Django

```powershell
cd d:\Nyoba
.\.venv\Scripts\python.exe manage.py check
```

**Keterangan:** Memastikan proyek TrailGear tidak memiliki kesalahan konfigurasi sebelum memulai praktikum.  
**Hasil yang diharapkan:** Menampilkan `System check identified no issues (0 silenced).`

> *[Tempel Screenshot: **Gambar 1.** Pemeriksaan awal proyek TrailGear dengan `manage.py check`]*

#### 1.2 Cek kondisi awal parameter logging PostgreSQL 18

```powershell
& "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -c "SHOW logging_collector; SHOW log_statement; SHOW log_connections; SHOW log_disconnections; SHOW log_line_prefix; SELECT pg_current_logfile();"
```

**Keterangan:** Memeriksa parameter audit bawaan PostgreSQL 18 sebelum diaktifkan (padanan dari `SHOW VARIABLES LIKE 'general_log%';` pada MySQL). Jika sebelumnya sudah sempat aktif, kamu bisa melihat nilai saat ini untuk dibandingkan dengan konfigurasi target pada Langkah 2.  
**Hasil yang diharapkan:** Menampilkan status parameter `logging_collector`, `log_statement`, `log_connections`, `log_disconnections`, `log_line_prefix`, dan `pg_current_logfile`.

> *[Tempel Screenshot: **Gambar 2.** Pemeriksaan kondisi awal parameter logging PostgreSQL 18]*

#### 1.3 Cek jumlah baris awal tabel audit aplikasi

```powershell
& "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -c "SELECT 'accounts_securityevent' AS tabel, count(*) FROM accounts_securityevent UNION ALL SELECT 'catalog_inventory_log', count(*) FROM catalog_inventory_log UNION ALL SELECT 'django_admin_log', count(*) FROM django_admin_log;"
```

**Keterangan:** Mencatat jumlah baris awal di tiga tabel audit aplikasi sebelum simulasi serangan dijalankan.  
**Hasil yang diharapkan:** Menampilkan jumlah baris untuk `accounts_securityevent`, `catalog_inventory_log` (`167` baris dari seeding katalog), dan `django_admin_log`.

> *[Tempel Screenshot: **Gambar 3.** Jumlah baris awal tabel audit aplikasi TrailGear]*

#### 1.4 Jalankan server pengembangan Django di jendela PowerShell terpisah

Buka jendela PowerShell baru, lalu jalankan:

```powershell
cd d:\Nyoba
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

**Keterangan:** Menjalankan aplikasi TrailGear pada `http://127.0.0.1:8000` agar dapat diuji melalui browser dan terminal secara bersamaan. Biarkan jendela ini tetap terbuka selama praktikum.

> *[Tempel Screenshot: **Gambar 4.** Server Django TrailGear berjalan pada `http://127.0.0.1:8000`]*

---

### Langkah 2. Aktivasi Audit Logging Database pada PostgreSQL 18 (Menutup Gap G1)

**Tujuan:** Mengaktifkan logging aktivitas database di PostgreSQL 18 agar seluruh koneksi (`log_connections`), pemutusan koneksi (`log_disconnections`), dan perintah SQL (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ERROR`/`FATAL`) terekam ke file log dengan informasi waktu, PID, user DBMS, nama database, dan IP client.

**Penjelasan:** PostgreSQL menyimpan perubahan parameter permanen melalui `ALTER SYSTEM` ke berkas `postgresql.auto.conf` di dalam `PGDATA` (`D:\Apps\PostgreSQL18\data`). Parameter `log_statement`, `log_connections`, `log_disconnections`, dan `log_line_prefix` langsung aktif setelah reload, sedangkan `logging_collector = 'on'` membutuhkan **restart penuh** PostgreSQL agar seluruh log diarahkan ke berkas `D:\Apps\PostgreSQL18\data\log\postgresql-YYYY-MM-DD.log`.

#### 2.1 Jalankan perintah `ALTER SYSTEM` untuk mengaktifkan parameter audit logging

```powershell
@'
ALTER SYSTEM SET logging_collector = 'on';
ALTER SYSTEM SET log_directory = 'log';
ALTER SYSTEM SET log_filename = 'postgresql-%Y-%m-%d.log';
ALTER SYSTEM SET log_statement = 'all';
ALTER SYSTEM SET log_connections = 'on';
ALTER SYSTEM SET log_disconnections = 'on';
ALTER SYSTEM SET log_line_prefix = '%m [%p] %q%u@%d %r ';
'@ | & "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -X -a
```

**Keterangan:**
- `logging_collector = 'on'`: mengaktifkan pengumpul log ke file harian di folder `D:\Apps\PostgreSQL18\data\log\`.
- `log_statement = 'all'`: mencatat seluruh pernyataan SQL (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DDL`) — padanan `general_log = ON` untuk sesi praktikum.
- `log_connections = 'on'` dan `log_disconnections = 'on'`: mencatat setiap koneksi masuk (termasuk percobaan login gagal `FATAL`) dan akhir sesi.
- `log_line_prefix = '%m [%p] %q%u@%d %r '`: memberi awalan tiap baris log berupa timestamp milidetik (`%m`), PID (`%p`), user DBMS (`%u`), nama database (`%d`), dan IP:port client (`%r`).
- *Catatan teknis:* Perintah dialirkan melalui *stdin* (`@' ... '@ | psql`) karena `ALTER SYSTEM` tidak boleh dijalankan di dalam satu blok transaksi implisit `psql -c "..."`.

**Hasil yang diharapkan:** Seluruh 7 perintah mengembalikan `ALTER SYSTEM` tanpa error.

> *[Tempel Screenshot: **Gambar 5.** Aktivasi parameter audit logging PostgreSQL melalui `ALTER SYSTEM`]*

#### 2.2 Restart PostgreSQL agar `logging_collector = 'on'` aktif sepenuhnya

```powershell
& "D:\Apps\PostgreSQL18\bin\pg_ctl.exe" -D "D:\Apps\PostgreSQL18\data" restart
```

*(Jika PostgreSQL berjalan sebagai Windows Service dan `pg_ctl` meminta hak Administrator, jalankan `Restart-Service postgresql-x64-18` di PowerShell **Run as Administrator**).*

**Keterangan:** Restart penuh diperlukan khusus agar parameter `logging_collector = 'on'` mulai menulis ke berkas `postgresql-YYYY-MM-DD.log`.  
**Hasil yang diharapkan:** PostgreSQL berhasil restart (`server started`) tanpa error.

> *[Tempel Screenshot: **Gambar 6.** Restart server PostgreSQL 18 untuk mengaktifkan `logging_collector`]*

#### 2.3 Verifikasi seluruh parameter audit logging aktif dan cek lokasi file log aktif

```powershell
& "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -c "SHOW logging_collector; SHOW log_statement; SHOW log_connections; SHOW log_disconnections; SHOW log_line_prefix; SELECT pg_current_logfile();"
```

**Keterangan:** Memastikan seluruh parameter audit sudah aktif dan menampilkan path file log yang sedang ditulis oleh PostgreSQL (padanan `SHOW VARIABLES LIKE 'general_log_file'` pada MySQL).  
**Hasil yang diharapkan:** `logging_collector = on`, `log_statement = all`, `log_connections = on`, `log_disconnections = on`, `log_line_prefix = %m [%p] %q%u@%d %r `, dan `pg_current_logfile` menampilkan `log/postgresql-YYYY-MM-DD.log`.

> *[Tempel Screenshot: **Gambar 7.** Verifikasi seluruh parameter audit logging PostgreSQL aktif dan lokasi file log]*

#### 2.4 Verifikasi tampilan status DBMS Audit di Dashboard Keamanan Admin (Browser)

1. Buka browser ke `http://127.0.0.1:8000/login/` lalu masuk sebagai **`admin1`**.
2. Buka menu **Keamanan** (`/dashboard/admin/security/`).
3. Perhatikan 4 kartu indikator DBMS di bagian atas halaman (`DBMS log_statement: all`, `DBMS log_connections: on`, `DBMS log_disconnections: on`, `DBMS logging_collector: on`).

**Keterangan:** Membuktikan bahwa Dashboard Admin TrailGear membaca langsung status konfigurasi audit PostgreSQL secara *real-time*.

> *[Tempel Screenshot: **Gambar 8.** Tampilan status parameter audit DBMS aktif pada halaman `/dashboard/admin/security/`]*

---

### Langkah 3. Verifikasi & Penjelasan Implementasi Audit Aplikasi (Menutup Gap G2 & G6)

**Tujuan:** Memahami mekanisme kode audit trail aplikasi TrailGear yang sudah terpasang (dual-sink `log_event()`, audit aksi sensitif Admin, dan file logging CSRF) serta memverifikasinya melalui unit test otomatis dan pengujian CSRF.

**Penjelasan:** Selain logging di level DBMS, aplikasi TrailGear mencatat peristiwa keamanan terstruktur melalui `accounts.security.log_event()`. Untuk menutup **Gap G2** (aksi sensitif Admin sebelumnya belum tercatat) dan **Gap G6** (kegagalan CSRF belum masuk ke file log persisten), proyek telah dilengkapi konstanta event `ADMIN_USER_UPDATED`, `ADMIN_SECURITY_OVERRIDE`, serta logger `django.security.csrf` yang diarahkan ke `logs/security.log`.

#### 3.1 Arsitektur & Cuplikan Kode Kunci yang Diimplementasikan

1. **Mekanisme Dual-Sink & Anti-Log Injection (`accounts/security.py`):**
   ```python
   def _safe_text(value, limit):
       if not value:
           return ""
       # Buang newline agar satu event tetap satu baris di file log.
       return " ".join(str(value).split())[:limit]

   def log_event(request, event_type, status, user=None, description=""):
       ip = client_ip(request) if request is not None else None
       ...
       SecurityEvent.objects.create(
           user=user if user_id else None,
           event_type=event_type,
           status=status,
           ip_address=ip,
           user_agent=user_agent,
           description=description,
       )
       logger.info("event=%s status=%s ip=%s user_id=%s desc=%s", ...)
   ```
   **Keterangan:** Menulis serentak ke database (`accounts_securityevent`) dan file rotasi (`logs/security.log`), sekaligus membersihkan karakter newline agar attacker tidak bisa menyisipkan baris log palsu (*CRLF / log injection*). Password, token CSRF, dan `sessionid` tidak pernah ditulis ke log.

2. **Konstanta Event Audit Admin (`accounts/models.py` + migrasi `0011`):**
   ```python
   ADMIN_USER_UPDATED = "ADMIN_USER_UPDATED"
   ADMIN_SECURITY_OVERRIDE = "ADMIN_SECURITY_OVERRIDE"
   ```
   Dipanggil pada `accounts/views.py` di `admin_user_manage` (ubah role/status aktif & unlock akun), `admin_user_toggle` (nonaktifkan/aktifkan akun), dan `admin_reset_ratelimit` (buka blokir IP / reset cache rate limit).

3. **Persistensi Log CSRF & HTTP Error (`config/settings.py`):**
   ```python
   "django.request": {
       "handlers": ["security_file", "console"],
       "level": "ERROR",
       "propagate": False,
   },
   "django.security.csrf": {
       "handlers": ["security_file", "console"],
       "level": "WARNING",
       "propagate": False,
   },
   ```

#### 3.2 Jalankan unit test verifikasi audit Admin & *User Access Review*

```powershell
.\.venv\Scripts\python.exe manage.py test accounts.tests.AdminUserManageAndRateLimitResetTests accounts.tests.UserAccessReviewTests -v 2
```

**Keterangan:** Memverifikasi secara otomatis bahwa aksi ubah role, toggle status akun, unlock akun, dan reset rate limit oleh Admin benar-benar tercatat sebagai `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE`, serta UAR mendeteksi privilege berlebih.  
**Hasil yang diharapkan:** Seluruh 7 test berstatus `ok` (`Ran 7 tests ... OK`).

> *[Tempel Screenshot: **Gambar 9.** Hasil eksekusi unit test audit aksi Admin dan UAR (`7 tests OK`)]*

#### 3.3 Verifikasi pencatatan kegagalan CSRF ke `logs/security.log`

```powershell
.\.venv\Scripts\python.exe -c "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); from django.test import Client; c=Client(HTTP_HOST='127.0.0.1', enforce_csrf_checks=True); r=c.post('/login/', {'username':'x','password':'y'}); print('HTTP Status:', r.status_code)"
Select-String -Path "d:\Nyoba\logs\security.log" -Pattern "django\.security\.csrf" | Select-Object -Last 3
```

**Keterangan:** Mengirim request `POST /login/` tanpa token/cookie CSRF untuk membuktikan penolakan `HTTP 403` sekaligus pencatatan persisten pada `logs/security.log`.  
**Hasil yang diharapkan:** Menampilkan `HTTP Status: 403` dan baris `WARNING | django.security.csrf | Forbidden (CSRF cookie not set.): /login/` pada `logs/security.log`.

> *[Tempel Screenshot: **Gambar 10.** Verifikasi penolakan CSRF 403 tercatat ke `logs/security.log`]*

---

### Langkah 4. Persiapan Akun & Data Uji Terisolasi (Aman untuk Data Produksi)

**Tujuan:** Membuat akun dan pesanan uji khusus agar seluruh simulasi attacker (Skenario A–E) tidak merusak data produksi (`admin1`, `kasir1`, dan `156` produk katalog).

**Penjelasan:** Pengujian keamanan yang baik harus terisolasi pada data uji. Kita membuat 3 akun uji (`m8_attacker` role Customer, `m8_victim` role Customer, `m8_disabled` nonaktif) serta 2 pesanan uji (`order_victim` untuk uji IDOR dan `order_kasir` untuk uji pelanggaran Maker–Checker).

#### 4.1 Buat akun uji dan pesanan uji sementara melalui Django

```powershell
@'
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from datetime import date, timedelta
from accounts.models import User
from accounts.roles import ROLE_CUSTOMER, assign_role
from catalog.models import Product
from rentals.models import RentalOrder, RentalOrderItem

PW = "TrailGear#2026!"
for uname in ("m8_attacker", "m8_victim", "m8_disabled"):
    User.objects.filter(username=uname).delete()

attacker = User.objects.create_user(username="m8_attacker", email="m8_attacker@lab.local", password=PW, first_name="Attacker", last_name="Lab")
assign_role(attacker, ROLE_CUSTOMER)

victim = User.objects.create_user(username="m8_victim", email="m8_victim@lab.local", password=PW, first_name="Victim", last_name="Lab")
assign_role(victim, ROLE_CUSTOMER)

disabled = User.objects.create_user(username="m8_disabled", email="m8_disabled@lab.local", password=PW, is_active=False)
assign_role(disabled, ROLE_CUSTOMER)

kasir1 = User.objects.get(username="kasir1")
prod = Product.objects.filter(is_active=True, available_stock__gt=2).first()
today = date.today()

def make_order(owner, full_name, nik):
    o = RentalOrder.objects.create(
        user=owner, full_name=full_name, phone_number="081200009999",
        id_card_number=nik, id_card_type="KTP",
        pickup_plan_date=today + timedelta(days=1), return_plan_date=today + timedelta(days=3),
        status=RentalOrder.Status.MENUNGGU_PEMBAYARAN,
        total_rental_fee=prod.price_per_day * 2, grand_total=prod.price_per_day * 2,
    )
    RentalOrderItem.objects.create(order=o, product=prod, unit_price=prod.price_per_day, quantity=1, duration_days=2)
    return o

o_victim = make_order(victim, "Victim Lab", "3201010101019999")
o_kasir  = make_order(kasir1, "Kasir Self Order", "3201010101018888")
print("Akun uji siap: m8_attacker, m8_victim, m8_disabled (Password:", PW, ")")
print("KODE ORDER VICTIM (catat untuk IDOR) :", o_victim.order_code)
print("KODE ORDER KASIR  (catat untuk M-C)  :", o_kasir.order_code)
'@ | .\.venv\Scripts\python.exe -
```

**Keterangan:** Catat dua kode booking yang dicetak di terminal (`KODE ORDER VICTIM` dan `KODE ORDER KASIR`) karena keduanya akan dipakai pada Langkah 8 dan Langkah 11.  
**Hasil yang diharapkan:** Menampilkan pesan akun uji siap beserta dua kode booking berformat `TG-YYYYMMDD-XXXX`.

> *[Tempel Screenshot: **Gambar 11.** Pembuatan akun uji dan 2 pesanan uji terisolasi]*

---

### Langkah 5. Simulasi Attacker A — *Reconnaissance & Authentication Abuse*

**Tujuan:** Menguji mekanisme anti brute-force (`HTTP 429` & `ACCOUNT_LOCKED`), anti *user enumeration*, serta penolakan login pada akun nonaktif dan terkunci, lalu memastikan seluruhnya tercatat di audit log.

**Penjelasan:** Attacker lazim memulai serangan dengan menebak akun terdaftar (*enumeration*) dan mengirim percobaan password berulang (*credential stuffing / brute-force*). TrailGear menerapkan batas 5 gagal per IP (`RATE_LIMIT_LOGIN`) dan kunci akun 15 menit setelah 10 gagal beruntun (`ACCOUNT_LOCKED`).

#### 5.1 Skenario A1 — Brute-Force Login (6× dari IP sama -> `429`, lalu 5× dari IP berbeda -> `ACCOUNT_LOCKED`)

```powershell
@'
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.core.cache import cache
from django.test import Client
from accounts.models import User

cache.clear()
c = Client(HTTP_HOST="127.0.0.1")
print("=== 6x gagal dari 127.0.0.1 ===")
for i in range(1, 7):
    r = c.post("/login/", {"username": "m8_victim", "password": f"Salah#{i}"})
    print(f"Percobaan #{i} (127.0.0.1) -> HTTP {r.status_code}")

print("=== 5x gagal lanjutan dari IP berbeda 10.0.0.99 (total 10 gagal akun) ===")
for i in range(1, 6):
    r = c.post("/login/", {"username": "m8_victim", "password": f"Dist#{i}"}, REMOTE_ADDR="10.0.0.99")
    print(f"Percobaan #{i} (10.0.0.99) -> HTTP {r.status_code}")

v = User.objects.get(username="m8_victim")
print(f"Status m8_victim -> failed_login_attempts={v.failed_login_attempts}, is_locked={v.is_locked}")
'@ | .\.venv\Scripts\python.exe -
```

**Keterangan:** Percobaan ke-6 dari IP `127.0.0.1` memicu rate limit `HTTP 429 Too Many Requests`. Percobaan terdistribusi dari IP `10.0.0.99` tetap terdeteksi di level akun dan mengunci `m8_victim` pada gagal ke-10 (`ACCOUNT_LOCKED`).  
**Hasil yang diharapkan:** Percobaan ke-6 menghasilkan `HTTP 429`, dan di akhir `is_locked=True`.

> *[Tempel Screenshot: **Gambar 12.** Hasil simulasi brute-force login (Skenario A1) memicu HTTP 429 dan Account Lockout]*

#### 5.2 Skenario A2 — *User Enumeration* (Akun Ada vs Akun Tidak Ada) di Browser

1. Reset cache rate limit sebentar agar browser bisa mencoba login:
   ```powershell
   .\.venv\Scripts\python.exe -c "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); from django.core.cache import cache; cache.clear(); print('Cache rate limit dibersihkan')"
   ```
2. Buka jendela **Incognito/Private Browser** ke `http://127.0.0.1:8000/login/`.
3. Masukkan username terdaftar **`m8_attacker`** dengan password salah (`Salah123!`) -> klik **Masuk**, amati pesan error.
4. Masukkan username fiktif **`ghost_user_9999`** dengan password salah (`Salah123!`) -> klik **Masuk**, bandingkan pesan error.

**Keterangan:** Kedua percobaan harus menampilkan pesan error generik yang identik (`"Username/email atau password tidak valid."`) sehingga attacker tidak bisa membedakan akun mana yang terdaftar.  
**Hasil yang diharapkan:** Pesan error identik pada kedua percobaan, dan keduanya tercatat sebagai `LOGIN_FAILED` di `accounts_securityevent`.

> *[Tempel Screenshot: **Gambar 13.** Respons pesan error generik identik pada uji User Enumeration (Skenario A2)]*

#### 5.3 Skenario A3 — Login ke Akun Nonaktif (`m8_disabled`) & Akun Terkunci (`m8_victim`)

1. Masih di Incognito Browser pada `/login/`, coba login memakai **`m8_disabled`** dengan password benar `TrailGear#2026!`.
2. Coba login memakai **`m8_victim`** (yang masih terkunci dari A1) dengan password benar `TrailGear#2026!`.

**Keterangan:** Menguji bahwa akun yang dinonaktifkan (`is_active=False`) maupun akun yang terkunci lockout tidak dapat masuk meskipun attacker mengetahui password yang benar.  
**Hasil yang diharapkan:** Keduanya ditolak tanpa sesi aktif; log mencatat `ACCOUNT_DISABLED` untuk `m8_disabled` dan `LOGIN_FAILED` (keterangan akun terkunci) untuk `m8_victim`.

> *[Tempel Screenshot: **Gambar 14.** Penolakan login pada akun nonaktif dan akun terkunci (Skenario A3)]*

---

### Langkah 6. Simulasi Attacker B — *Privilege Abuse* (Akses Langsung via URL)

**Tujuan:** Menguji apakah kontrol RBAC (`@role_required`) menolak akses langsung melalui URL (bukan sekadar menyembunyikan tombol UI) dan mencatat setiap percobaan sebagai `ACCESS_DENIED`.

**Penjelasan:** Attacker sering mencoba menebak dan mengakses langsung endpoint sensitif (`/dashboard/cashier/`, `/dashboard/admin/`, `/dashboard/admin/security/`) dengan akun berhak akses rendah.

#### 6.1 Skenario B1 & B2 — Customer (`m8_attacker`) Mengakses Langsung URL Kasir & Admin di Browser

1. Di Incognito Browser, login sebagai **`m8_attacker`** (`TrailGear#2026!`, role **Customer**).
2. Ketik langsung di address bar secara berurutan:
   - `http://127.0.0.1:8000/dashboard/cashier/` *(Skenario B1 — Customer -> Kasir)*
   - `http://127.0.0.1:8000/dashboard/orders/` *(Skenario B1)*
   - `http://127.0.0.1:8000/dashboard/admin/` *(Skenario B2 — Customer -> Admin)*
   - `http://127.0.0.1:8000/dashboard/admin/security/` *(Skenario B2)*
   - `http://127.0.0.1:8000/dashboard/admin/users/add/` *(Skenario B2)*

**Keterangan:** Setiap URL yang diakses langsung oleh role `Customer` harus memunculkan halaman `403 Forbidden` dan menulis event `ACCESS_DENIED (BLOCKED)` berisi `path`, `role=Customer`, dan role yang dibutuhkan.  
**Hasil yang diharapkan:** Seluruh 5 percobaan menampilkan halaman **`403 Forbidden`**.

> *[Tempel Screenshot: **Gambar 15.** Halaman `403 Forbidden` saat Customer (`m8_attacker`) mengakses langsung URL `/dashboard/admin/security/` (Skenario B1 & B2)]*

#### 6.2 Skenario B3 — Cashier (`kasir1`) Mengakses Langsung URL & Aksi Admin

1. Logout dari `m8_attacker`, lalu login sebagai **`kasir1`** (role **Cashier**).
2. Akses langsung di address bar:
   - `http://127.0.0.1:8000/dashboard/admin/`
   - `http://127.0.0.1:8000/dashboard/admin/users/`
3. Uji juga `POST` langsung ke aksi sensitif Admin (`/dashboard/admin/security/reset-ratelimit/`) via PowerShell:
   ```powershell
   .\.venv\Scripts\python.exe -c "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); from django.test import Client; from accounts.models import User; c=Client(HTTP_HOST='127.0.0.1'); c.force_login(User.objects.get(username='kasir1')); r=c.post('/dashboard/admin/security/reset-ratelimit/', {'mode':'all'}); print('Cashier POST reset-ratelimit -> HTTP', r.status_code)"
   ```

**Keterangan:** Membuktikan prinsip *Least Privilege*: Kasir hanya memiliki akses operasional kasir dan diblokir dari seluruh fungsi administratif.  
**Hasil yang diharapkan:** Seluruh percobaan mengembalikan **`HTTP 403 Forbidden`** dan mencatat `ACCESS_DENIED` dengan `role=Cashier butuh=Admin`.

> *[Tempel Screenshot: **Gambar 16.** Penolakan akses `403 Forbidden` saat Kasir (`kasir1`) mengakses fungsi Admin (Skenario B3)]*

---

### Langkah 7. Simulasi Attacker C — *Input Attack* (SQL Injection & XSS)

**Tujuan:** Menguji ketahanan aplikasi terhadap payload SQL Injection dan Cross-Site Scripting (XSS) pada form login, pencarian katalog, serta profil pengguna, sekaligus mengevaluasi apakah percobaan tersebut meninggalkan jejak di log aplikasi dan/atau log DBMS.

**Penjelasan:** Django ORM menggunakan *parameterized query* untuk mencegah SQL Injection dan *template auto-escaping* untuk mencegah XSS. Pengujian ini juga bertujuan membuktikan secara jujur *blind spot* log aplikasi pada halaman pencarian publik (`C2`/`C3`) yang ternyata tetap tertangkap oleh log DBMS PostgreSQL (`log_statement = 'all'`).

#### 7.1 Skenario C1 — SQL Injection pada Form Login

1. Di Incognito Browser (kondisi logout), buka `http://127.0.0.1:8000/login/`.
2. Isi **Email atau Username** dengan payload: `' OR 1=1 --` dan password bebas (`anything`), lalu klik **Masuk**.

**Keterangan:** Menguji apakah payload klasik SQLi mampu membypass autentikasi.  
**Hasil yang diharapkan:** Login gagal dengan pesan error generik (tidak bisa masuk), dan `accounts_securityevent` mencatat `LOGIN_FAILED` dengan `description: identifier="' OR 1=1 --"`.

> *[Tempel Screenshot: **Gambar 17.** Payload SQL Injection `' OR 1=1 --` pada form login ditolak aman (Skenario C1)]*

#### 7.2 Skenario C2 — SQL Injection pada Pencarian Katalog

Buka di browser:
```text
http://127.0.0.1:8000/products/?q=' OR '1'='1' UNION SELECT username,password FROM accounts_user --
```

**Keterangan:** Menguji pencarian katalog terhadap percobaan `UNION SELECT` ke tabel user.  
**Hasil yang diharapkan:** Halaman tetap `HTTP 200` (menampilkan 0 produk cocok, tidak terjadi error SQL 500 maupun kebocoran hash `pbkdf2_sha256`). Di log aplikasi tidak muncul event khusus (*Gap G5*), namun query ter-escape (`''`) terekam di file log PostgreSQL.

> *[Tempel Screenshot: **Gambar 18.** Hasil pencarian katalog dengan payload SQL Injection `UNION SELECT` (Skenario C2)]*

#### 7.3 Skenario C3 — Reflected XSS & Stored XSS

1. **Reflected XSS:** Buka di browser:
   ```text
   http://127.0.0.1:8000/products/?q=<script>alert('xss')</script>
   ```
   Amati bahwa tidak ada pop-up `alert` yang muncul; tag `<script>` tampil sebagai teks biasa yang ter-escape.
2. **Stored XSS:** Login sebagai `m8_attacker` (`TrailGear#2026!`), buka `http://127.0.0.1:8000/settings/`, ubah **Nama Depan** menjadi `<img src=x onerror=alert(1)>`, lalu klik **Simpan Perubahan** dan muat ulang halaman.

**Keterangan:** Memastikan *auto-escaping* Django menetralkan tag HTML/JS berbahaya baik pada respons langsung (*reflected*) maupun data yang disimpan ke database (*stored*).  
**Hasil yang diharapkan:** Tidak ada dialog JavaScript yang tereksekusi; teks `<img src=x onerror=alert(1)>` di-render sebagai teks literal aman (`&lt;img ...&gt;`), sementara perintah `UPDATE accounts_user` tercatat di log DBMS PostgreSQL.

> *[Tempel Screenshot: **Gambar 19.** Payload XSS ter-escape sebagai teks biasa tanpa eksekusi script (Skenario C3)]*

---

### Langkah 8. Simulasi Attacker D — *Business Logic Abuse* & Verifikasi Audit Admin

**Tujuan:** Menguji perlindungan terhadap *Insecure Direct Object Reference* (IDOR) pesanan milik user lain, perubahan status tanpa hak, pelanggaran *Separation of Duties* (Maker–Checker), serta verifikasi pencatatan aksi sensitif Admin (`G2-VERIFY`).

**Penjelasan:** Selain celah teknis, attacker sering menyalahgunakan alur bisnis dengan mengganti kode booking milik korban di URL atau menyetujui transaksi buatannya sendiri.

#### 8.1 Skenario D1 & D2 — IDOR Read & IDOR Write ke Pesanan Milik `m8_victim`

Ganti `<KODE_VICTIM>` dengan kode pesanan `m8_victim` dari Langkah 4.1:

1. Dalam keadaan login sebagai **`m8_attacker`** di browser, akses langsung URL:
   - `http://127.0.0.1:8000/orders/<KODE_VICTIM>/` *(D1 — mengintip nota korban)*
   - `http://127.0.0.1:8000/orders/<KODE_VICTIM>/proof/` *(D1 — mengintip bukti transfer korban)*
2. Uji *IDOR Write* (mencoba membatalkan dan mengunggah bukti pada pesanan milik korban) lewat PowerShell:
   ```powershell
   $KODE_VICTIM = "<KODE_VICTIM>"
   .\.venv\Scripts\python.exe -c "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); from django.test import Client; from accounts.models import User; c=Client(HTTP_HOST='127.0.0.1'); c.force_login(User.objects.get(username='m8_attacker')); print('IDOR cancel ->', c.post('/orders/$KODE_VICTIM/cancel/').status_code); print('IDOR upload-proof ->', c.post('/orders/$KODE_VICTIM/upload-proof/').status_code)"
   ```

**Keterangan:** Memverifikasi bahwa kontrol kepemilikan (`order.user_id != request.user.pk`) memblokir seluruh upaya baca/ubah pesanan user lain dan mencatatnya sebagai `ACCESS_DENIED`.  
**Hasil yang diharapkan:** Seluruh percobaan D1 & D2 mengembalikan **`403 Forbidden`** dan status pesanan korban tetap `MENUNGGU_PEMBAYARAN`.

> *[Tempel Screenshot: **Gambar 20.** Penolakan IDOR Read & Write (`403 Forbidden`) terhadap pesanan milik `m8_victim` (Skenario D1 & D2)]*

#### 8.2 Skenario D3 — Unauthorized Status Change & Pelanggaran Maker–Checker (*Self-Approval*)

Ganti `<KODE_VICTIM>` dan `<KODE_KASIR>` sesuai output Langkah 4.1:

```powershell
$KODE_VICTIM = "<KODE_VICTIM>"
$KODE_KASIR  = "<KODE_KASIR>"
@'
import os, sys, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.test import Client
from accounts.models import User
from rentals.models import RentalOrder

k_vic, k_kas = sys.argv[1], sys.argv[2]
c_att = Client(HTTP_HOST="127.0.0.1")
c_att.force_login(User.objects.get(username="m8_attacker"))
print("Customer confirm order -> HTTP", c_att.post(f"/dashboard/orders/{k_vic}/confirm/").status_code)

c_kas = Client(HTTP_HOST="127.0.0.1")
c_kas.force_login(User.objects.get(username="kasir1"))
r_mc = c_kas.post(f"/dashboard/orders/{k_kas}/confirm/", follow=True)
o_kas = RentalOrder.objects.get(order_code=k_kas)
print("Kasir self-approve status tetap ->", o_kas.status, "| Pesan Maker-Checker muncul:", "Maker-Checker" in r_mc.content.decode())
'@ | .\.venv\Scripts\python.exe - $KODE_VICTIM $KODE_KASIR
```

**Keterangan:** Menguji dua hal sekaligus: (1) Customer mencoba mengonfirmasi pembayaran (harus `403`), dan (2) Kasir (`kasir1`) mencoba menyetujui pesanan yang dibuatnya sendiri (harus diblokir oleh kontrol *Maker–Checker* dan mencatat `MAKER_CHECKER_VIOLATION`).  
**Hasil yang diharapkan:** Customer -> `HTTP 403`; Kasir *self-approve* ditolak dengan status pesanan tetap `MENUNGGU_PEMBAYARAN` dan `Pesan Maker-Checker muncul: True`.

> *[Tempel Screenshot: **Gambar 21.** Penolakan konfirmasi oleh Customer dan pemblokiran pelanggaran Maker–Checker oleh Kasir (Skenario D3)]*

#### 8.3 Skenario D4 — Akses Tanpa Hak ke Manajemen Produk/Stok Admin

Dalam keadaan login sebagai `kasir1` di browser, akses langsung:
- `http://127.0.0.1:8000/dashboard/admin/products/` -> harus `403 Forbidden` (tercatat `ACCESS_DENIED`).
- `http://127.0.0.1:8000/admin/catalog/product/1/change/` -> harus redirect ke `/admin/login/` (`is_staff=False`).

> *[Tempel Screenshot: **Gambar 22.** Penolakan akses manajemen produk/stok bagi non-Admin (Skenario D4)]*

#### 8.4 Verifikasi Penutupan Gap G2 (`G2-VERIFY`) — Aksi Sensitif Admin Kini Tercatat

1. Buka jendela browser yang login sebagai **`admin1`**.
2. Buka **Users** (`/dashboard/admin/users/`), klik **Nonaktifkan** pada akun uji `m8_attacker`, lalu klik **Aktifkan** kembali.
3. Buka **Keamanan** (`/dashboard/admin/security/`), masukkan IP `10.0.0.99` pada form *Buka Blokir / Reset Rate Limit IP* lalu klik **Buka Blokir / Reset IP Ini**.

**Keterangan:** Memastikan aksi sensitif oleh Admin kini meninggalkan jejak audit `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE` sehingga penyalahgunaan akun Admin (*insider threat*) dapat dilacak.  
**Hasil yang diharapkan:** Di tabel Log Keamanan langsung muncul baris `ADMIN_USER_UPDATED` (`action=toggle_active`) dan `ADMIN_SECURITY_OVERRIDE` (`action=reset_ratelimit_ip target_ip=10.0.0.99`).

> *[Tempel Screenshot: **Gambar 23.** Pencatatan event `ADMIN_USER_UPDATED` dan `ADMIN_SECURITY_OVERRIDE` setelah aksi Admin (`G2-VERIFY`)]*

---

### Langkah 9. Simulasi Attacker E — *Session Abuse*

**Tujuan:** Menguji keamanan manajemen sesi ketika halaman terproteksi diakses setelah logout, ketika cookie `sessionid` lama dikirim ulang (*session replay*), dan ketika cookie `sessionid` palsu dikirim.

**Penjelasan:** TrailGear menyimpan sesi di tabel database `django_session`. Saat `POST /logout/` dipanggil, baris sesi dihapus dari database sehingga cookie lama tidak dapat dipakai kembali.

#### 9.1 Skenario E1, E2, dan E3 — Post-Logout Access, Session Replay, dan Forged Session Cookie

```powershell
@'
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.core.cache import cache
from django.test import Client

cache.clear()
c = Client(HTTP_HOST="127.0.0.1")
c.post("/login/", {"username": "m8_attacker", "password": "TrailGear#2026!"})
old_sid = c.cookies["sessionid"].value
print("Session ID aktif sebelum logout :", old_sid[:12] + "...")

r_out = c.post("/logout/")
r_e1  = c.get("/settings/")
print(f"E1 (akses /settings/ pasca-logout)    -> HTTP {r_e1.status_code} redirect ke {r_e1.url}")

c_replay = Client(HTTP_HOST="127.0.0.1")
c_replay.cookies["sessionid"] = old_sid
r_e2 = c_replay.get("/settings/")
print(f"E2 (replay sessionid lama)            -> HTTP {r_e2.status_code} redirect ke {r_e2.url}")

c_forged = Client(HTTP_HOST="127.0.0.1")
c_forged.cookies["sessionid"] = "forged_invalid_session_token_12345"
r_e3 = c_forged.get("/dashboard/admin/")
print(f"E3 (forged sessionid ke /admin/)      -> HTTP {r_e3.status_code} redirect ke {r_e3.url}")
'@ | .\.venv\Scripts\python.exe -
```

**Keterangan:** Menguji tiga vektor penyalahgunaan sesi sekaligus. `LOGOUT` tercatat di `accounts_securityevent`, sementara `E2` dan `E3` ditolak `HTTP 302` ke `/login/` tanpa menghasilkan alert di `accounts_securityevent` (*blind spot* Gap G4 — namun lookup `django_session` tetap terekam di log DBMS PostgreSQL).  
**Hasil yang diharapkan:** E1, E2, dan E3 seluruhnya ditolak dan diarahkan (`HTTP 302`) ke `/login/?next=...`.

> *[Tempel Screenshot: **Gambar 24.** Pengujian Session Abuse E1, E2 (Session Replay), dan E3 (Forged Cookie)]*

---

### Langkah 10. Simulasi Attacker F — Aktivitas Normal & Mencurigakan pada DBMS PostgreSQL

**Tujuan:** Memenuhi tugas inti Modul VIII pada level database: menjalankan query normal (`SELECT` & `INSERT`), mensimulasikan aktivitas destruktif aman (`DROP TABLE` pada tabel dummy), menguji percobaan penghapusan jejak audit (`DELETE FROM accounts_securityevent`) oleh role terbatas, serta mensimulasikan login gagal langsung ke PostgreSQL.

**Penjelasan:** Pengujian DDL destruktif **wajib** dilakukan hanya pada tabel dummy `uji_audit_tmp` agar tabel produksi TrailGear tidak rusak.

#### 10.1 Skenario F1 — Aktivitas Data Normal (`CREATE`, `INSERT`, `SELECT`)

```powershell
@'
CREATE TABLE IF NOT EXISTS uji_audit_tmp (id SERIAL PRIMARY KEY, nama TEXT, nominal INT, created_at TIMESTAMPTZ DEFAULT NOW());
INSERT INTO uji_audit_tmp (nama, nominal) VALUES ('Andi Uji Modul 8', 100000);
SELECT id, nama, nominal FROM uji_audit_tmp;
SELECT id, name, available_stock FROM catalog_product ORDER BY id LIMIT 3;
'@ | & "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -X -a
```

**Keterangan:** Menjalankan operasi normal `INSERT` dan `SELECT` untuk dibuktikan kemunculannya di file log PostgreSQL (padanan tugas `INSERT` & `SELECT` pada Modul VIII).  
**Hasil yang diharapkan:** Data `'Andi Uji Modul 8'` berhasil disisipkan dan ditampilkan bersama 3 baris pertama `catalog_product`.

> *[Tempel Screenshot: **Gambar 25.** Aktivitas data normal `CREATE`, `INSERT`, dan `SELECT` pada PostgreSQL (Skenario F1)]*

#### 10.2 Skenario F2 — Aktivitas Destruktif Aman (`DROP TABLE` Dummy & Percobaan `DELETE` Tabel Audit)

```powershell
@'
DROP TABLE uji_audit_tmp;
SET ROLE role_kasir_db;
DELETE FROM accounts_securityevent;
RESET ROLE;
'@ | & "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -X -a
```

**Keterangan:** Mensimulasikan dua aktivitas berisiko tinggi: (1) penghapusan tabel pada tabel dummy `uji_audit_tmp` (padanan `DROP TABLE transaksi;` di Modul VIII secara aman), dan (2) percobaan menghapus jejak audit oleh `role_kasir_db` yang harus ditolak oleh kontrol *Least Privilege* DBMS.  
**Hasil yang diharapkan:** `DROP TABLE uji_audit_tmp` menghasilkan `DROP TABLE`; `DELETE FROM accounts_securityevent` ditolak dengan **`ERROR: permission denied for table accounts_securityevent`**.

> *[Tempel Screenshot: **Gambar 26.** Eksekusi `DROP TABLE` tabel dummy dan penolakan `DELETE` tabel audit oleh `role_kasir_db` (Skenario F2)]*

#### 10.3 Skenario F3 — Login Gagal Langsung ke Database PostgreSQL

```powershell
$env:PGPASSWORD = "SalahPasswordModul8!"
& "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U normal_user -d TrailGear_auth -c "SELECT 1;"
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
```

**Keterangan:** Mensimulasikan upaya akses tidak sah (password salah) langsung ke port PostgreSQL `5432` menggunakan role `normal_user` (padanan tugas login gagal ke DBMS pada Modul VIII).  
**Hasil yang diharapkan:** Koneksi ditolak dengan **`FATAL: password authentication failed for user "normal_user"`** dan tercatat di log PostgreSQL lengkap dengan aturan `pg_hba.conf`.

> *[Tempel Screenshot: **Gambar 27.** Penolakan login gagal langsung ke PostgreSQL (Skenario F3)]*

---

### Langkah 11. Korelasi Serangan Berantai, Analisis 3 Sumber Log & Pembersihan Pasca-Praktikum

**Tujuan:** Mensimulasikan serangan berantai 6 tahap dari satu IP khusus, merekonstruksi linimasa insiden secara kronologis dengan menggabungkan log Aplikasi dan log DBMS, menyaring aktivitas mencurigakan, lalu membersihkan data uji.

**Penjelasan:** Dalam investigasi insiden nyata (*incident reconstruction*), satu log saja sering kali tidak cukup. Dengan mengorelasikan **`timestamp` + `ip_address` + `user_id`** lintas 3 sumber log (`accounts_securityevent`, `logs/security.log`, dan file log PostgreSQL), seluruh tahapan serangan dapat disusun ulang utuh.

#### 11.1 Jalankan Skenario Serangan Berantai 6 Tahap dari IP Khusus (`198.51.100.77`)

Ganti `<KODE_VICTIM>` sesuai output Langkah 4.1:

```powershell
$KODE_VICTIM = "<KODE_VICTIM>"
@'
import os, sys, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.core.cache import cache
from django.test import Client
from accounts.models import User

kode_victim = sys.argv[1]
cache.clear()
att = User.objects.get(username="m8_attacker")
att.reset_login_lock()

ip = "198.51.100.77"
c = Client(HTTP_HOST="127.0.0.1")

# Tahap 1: 3x gagal login
for i in range(3):
    c.post("/login/", {"username": "m8_attacker", "password": f"Guess#{i}"}, REMOTE_ADDR=ip)
# Tahap 2: Login berhasil
c.post("/login/", {"username": "m8_attacker", "password": "TrailGear#2026!"}, REMOTE_ADDR=ip)
# Tahap 3: Privilege abuse ke Kasir & Admin
c.get("/dashboard/cashier/", REMOTE_ADDR=ip)
c.get("/dashboard/admin/security/", REMOTE_ADDR=ip)
# Tahap 4: IDOR & unauthorized confirm ke pesanan korban
c.get(f"/orders/{kode_victim}/", REMOTE_ADDR=ip)
c.post(f"/orders/{kode_victim}/cancel/", REMOTE_ADDR=ip)
c.post(f"/dashboard/orders/{kode_victim}/confirm/", REMOTE_ADDR=ip)
# Tahap 5: Probing SQLi di pencarian katalog (blind spot App -> tertangkap di DBMS)
c.get("/products/", {"q": "' OR 1=1 --"}, REMOTE_ADDR=ip)
# Tahap 6: Logout + Session Replay cookie lama
old_sid = c.cookies["sessionid"].value
c.post("/logout/", REMOTE_ADDR=ip)
c2 = Client(HTTP_HOST="127.0.0.1")
c2.cookies["sessionid"] = old_sid
r_rep = c2.get("/settings/", REMOTE_ADDR=ip)
print(f"Serangan berantai selesai dari IP {ip}. Stage 6b replay -> HTTP {r_rep.status_code} ({r_rep.url})")
'@ | .\.venv\Scripts\python.exe - $KODE_VICTIM
```

**Keterangan:** Memakai IP dokumentasi RFC 5737 (`198.51.100.77`) agar linimasa 6 tahap serangan bersih dan mudah difilter saat korelasi SQL.  
**Hasil yang diharapkan:** Menampilkan `Serangan berantai selesai dari IP 198.51.100.77. Stage 6b replay -> HTTP 302 (/login/?next=/settings/)`.

#### 11.2 Rekonstruksi Linimasa Serangan Berantai via Query SQL di `accounts_securityevent`

```powershell
@'
SELECT
    to_char(e.timestamp AT TIME ZONE 'Asia/Jakarta', 'YYYY-MM-DD HH24:MI:SS.MS') AS waktu_wib,
    e.ip_address,
    COALESCE(u.username, 'anonymous') AS actor,
    e.event_type,
    e.status,
    e.description
FROM accounts_securityevent e
LEFT JOIN accounts_user u ON u.id = e.user_id
WHERE e.ip_address = '198.51.100.77'
ORDER BY e.timestamp ASC;
'@ | & "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -X
```

**Keterangan:** Menghubungkan 3 kegagalan pra-login (`anonymous`, `LOGIN_FAILED`) dengan sesi pasca-login (`m8_attacker`, `LOGIN_SUCCESS` -> `5x ACCESS_DENIED` -> `LOGOUT`) melalui kunci korelasi `ip_address` + `timestamp`.  
**Hasil yang diharapkan:** Menampilkan 10 baris berurutan secara kronologis dari Tahap 1 hingga Tahap 6a.

> *[Tempel Screenshot: **Gambar 28.** Output query SQL korelasi linimasa serangan berantai dari IP `198.51.100.77`]*

#### 11.3 Pemeriksaan Sumber Log 1 — Dashboard Keamanan Admin (Browser)

Buka browser (`admin1`) pada `http://127.0.0.1:8000/dashboard/admin/security/`, lalu gunakan filter pencarian `198.51.100.77` atau filter Status `Blocked` / `Failure` untuk melihat tabel log keamanan secara visual.

> *[Tempel Screenshot: **Gambar 29.** Tampilan hasil audit log serangan pada halaman `/dashboard/admin/security/`]*

#### 11.4 Pemeriksaan Sumber Log 2 — Filter Aktivitas Mencurigakan pada `logs/security.log`

```powershell
Select-String -Path "d:\Nyoba\logs\security.log" -Pattern "BLOCKED|FAILURE|django\.security\.csrf|ADMIN_USER_UPDATED|ADMIN_SECURITY_OVERRIDE" | Select-Object -Last 25
```

**Keterangan:** Memeriksa berkas log rotasi aplikasi untuk menyaring seluruh event `BLOCKED`, `FAILURE`, kegagalan `CSRF`, dan perubahan oleh Admin.  
**Hasil yang diharapkan:** Menampilkan baris-baris log terstruktur lengkap dengan timestamp, IP, `user_id`, dan keterangan insiden.

> *[Tempel Screenshot: **Gambar 30.** Hasil filter aktivitas mencurigakan pada berkas `logs/security.log`]*

#### 11.5 Pemeriksaan Sumber Log 3 — Baca & Filter Log Audit PostgreSQL 18

```powershell
$PG_LOG = (Get-ChildItem "D:\Apps\PostgreSQL18\data\log\postgresql-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Write-Host "File log aktif: $PG_LOG"
Select-String -Path $PG_LOG -Pattern "uji_audit_tmp|permission denied|password authentication failed|OR 1=1|alert\(1\)|django_session" | Select-Object -Last 25
```

*(Fallback jika belum restart service dan log masih di Windows Event Log:)*
```powershell
Get-EventLog -LogName Application -Source "*PostgreSQL*" -Newest 200 | Where-Object { $_.Message -match "uji_audit_tmp|permission denied|password authentication failed|OR 1=1|django_session" } | Select-Object -First 15 TimeGenerated, EntryType, Message | Format-List
```

**Keterangan:** Menyaring file log PostgreSQL untuk membuktikan bahwa `CREATE`/`INSERT`/`SELECT` (`F1`), `DROP TABLE` & `ERROR: permission denied` (`F2`), `FATAL: password authentication failed` (`F3`), probing SQLi Tahap 5 (`LIKE UPPER('%'' OR 1=1 --%')`), serta *session replay* Tahap 6b (`SELECT django_session` sesaat setelah `DELETE django_session`) seluruhnya terekam di level DBMS.  
**Hasil yang diharapkan:** Seluruh kejadian DBMS dan *blind spot* Tahap 5 & 6b terlihat jelas lengkap dengan awalan timestamp ms, PID, `user@TrailGear_auth`, dan IP:port client.

> *[Tempel Screenshot: **Gambar 31.** Bukti log audit PostgreSQL menampilkan `INSERT`, `DROP TABLE`, `ERROR: permission denied`, `FATAL`, dan query Tahap 5/6b]*

#### 11.6 Rekap Agregasi Tabel `accounts_securityevent`

```powershell
& "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -c "SELECT event_type, status, count(*) AS jumlah FROM accounts_securityevent GROUP BY event_type, status ORDER BY event_type, status;"
```

**Keterangan:** Menampilkan ringkasan total peristiwa per jenis event yang berhasil dicatat selama seluruh sesi pengujian.

> *[Tempel Screenshot: **Gambar 32.** Rekap agregasi `accounts_securityevent` selama sesi praktikum]*

#### 11.7 Pembersihan Data Uji & Penyesuaian Produksi Pasca-Praktikum

Jalankan langkah ini **setelah semua screenshot selesai diambil** agar database bersih kembali dan disk tidak cepat penuh oleh `log_statement = 'all'`:

```powershell
# 1. Hapus akun uji, pesanan uji, dan reset cache rate limit
@'
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from django.core.cache import cache
from accounts.models import User
from rentals.models import RentalOrder

cache.clear()
RentalOrder.objects.filter(user__username__in=["m8_attacker", "m8_victim", "m8_disabled", "kasir1"]).delete()
User.objects.filter(username__in=["m8_attacker", "m8_victim", "m8_disabled"]).delete()
print("Data uji sementara berhasil dibersihkan. Sisa user:", list(User.objects.values_list("username", flat=True)))
'@ | .\.venv\Scripts\python.exe -

# 2. (Opsional pasca-penilaian) Turunkan log_statement dari 'all' ke 'mod' agar hemat disk di produksi
@'
DROP TABLE IF EXISTS uji_audit_tmp;
ALTER SYSTEM SET log_statement = 'mod';
SELECT pg_reload_conf();
SHOW log_statement;
'@ | & "D:\Apps\PostgreSQL18\bin\psql.exe" -h 127.0.0.1 -U postgres -d TrailGear_auth -X -a
```

**Keterangan:** Membersihkan seluruh akun dan pesanan uji tanpa menyentuh `156` produk, `admin1`, maupun `kasir1`, serta menurunkan `log_statement` ke `'mod'` agar aktivitas tulis (`INSERT`/`UPDATE`/`DELETE`/`DDL`) tetap tercatat tanpa membanjiri disk oleh query `SELECT` rutin.

---

## BAB IV MATRIKS HASIL PENGUJIAN & KORELASI SERANGAN

### 4.1 Matriks Hasil Eksekusi 20 Skenario Pengujian

| Kode | Aktivitas Attacker | Target | Respons Aktual Aplikasi / DBMS | Kontrol Keamanan | Audit Log / Event Tercatat | Deteksi dari Log | Status | Severity (Jika Lemah) |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **A1** | Brute-force 6× IP sama + 5× IP beda pada `m8_victim` | `POST /login/` | Ke-6 `HTTP 429`; ke-10 `locked=True` | `ratelimit.login_blocked()` + `register_failed_login()` | `LOGIN_FAILED` (10×), `RATE_LIMIT_LOGIN[BLOCKED]`, `ACCOUNT_LOCKED[BLOCKED]` | **Ya** (App + File) | **PASS** | High |
| **A2** | Bandingkan login akun ada vs fiktif | `POST /login/` | Keduanya `HTTP 200`, pesan error identik | Pesan generik + dummy hash | 2× `LOGIN_FAILED[FAILURE]` dengan `identifier` | **Ya** (App + File) | **PASS** | Medium |
| **A3** | Login password benar ke akun nonaktif & terkunci | `POST /login/` | Keduanya ditolak (`HTTP 200`, tanpa sesi) | Cek `is_active` & `is_locked` | `ACCOUNT_DISABLED[FAILURE]` & `LOGIN_FAILED` (akun terkunci) | **Ya** (App + File) | **PASS** | Medium |
| **B1** | Customer akses langsung 3 URL Kasir | `/dashboard/cashier/`, `/orders/`, `/lookup/` | `HTTP [403, 403, 403]` | `@role_required(Cashier, Admin)` | 3× `ACCESS_DENIED[BLOCKED]` (`role=Customer`) | **Ya** (App + File) | **PASS** | High |
| **B2** | Customer akses langsung 3 URL Admin | `/dashboard/admin/`, `/security/`, `/users/add/` | `HTTP [403, 403, 403]` | `@role_required(Admin)` | 3× `ACCESS_DENIED[BLOCKED]` (`role=Customer`) | **Ya** (App + File) | **PASS** | Critical |
| **B3** | Cashier akses langsung URL & POST Admin | `/dashboard/admin/`, `/users/`, `POST /reset-ratelimit/` | `HTTP [403, 403, 403]` | `@role_required(Admin)` | 3× `ACCESS_DENIED[BLOCKED]` (`role=Cashier`) | **Ya** (App + File) | **PASS** | High |
| **C1** | SQLi `' OR 1=1 --` di form login | `POST /login/` | `HTTP 200` gagal login (tidak bypass) | Django ORM parameterized query | App: `LOGIN_FAILED` (`identifier="' OR 1=1 --"`); DBMS: `SELECT` ter-escape | **Ya** (App + DBMS) | **PASS** | Critical |
| **C2** | SQLi `UNION SELECT` di pencarian katalog | `GET /products/?q=...` | `HTTP 200`, 0 produk, tidak error/bocor | Django ORM `Q(...__icontains)` | App: tidak ada; DBMS: `SELECT ... LIKE` terekam (`log_statement=all`) | **Tidak di App / Ya di DBMS** | **PASS** | Medium |
| **C3** | Reflected XSS & Stored XSS (`<script>`, `<img onerror>`) | `GET /products/`, `POST /settings/` | Ter-escape aman (`&lt;script&gt;`, `&lt;img`) | Django Template Auto-Escaping | App: tidak ada; DBMS: `UPDATE accounts_user` terekam | **Tidak di App / Ya di DBMS** | **PASS** | Medium |
| **D1** | IDOR Read detail & bukti bayar pesanan korban | `GET /orders/<kode>/` & `/proof/` | `HTTP 403`, `HTTP 403` | Cek kepemilikan `order.user_id` | 2× `ACCESS_DENIED[BLOCKED]` | **Ya** (App + File) | **PASS** | High |
| **D2** | IDOR Write batalkan & unggah bukti pesanan korban | `POST /orders/<kode>/cancel/` & `upload-proof/` | `HTTP 403`, `HTTP 403`; status utuh | Cek kepemilikan + atomik | 2× `ACCESS_DENIED[BLOCKED]` | **Ya** (App + File) | **PASS** | High |
| **D3** | Customer confirm & Kasir *self-approve* pesanan sendiri | `POST /dashboard/orders/<kode>/confirm/` | Customer `403`; Kasir ditolak Maker–Checker | `@role_required` + Maker != Checker | `ACCESS_DENIED` + `MAKER_CHECKER_VIOLATION[BLOCKED]` | **Ya** (App + File) | **PASS** | High |
| **D4** | Customer/Cashier akses kelola produk Admin & `/admin/` | `/dashboard/admin/products/`, `/admin/...` | Dashboard `403`; `/admin/` `302` login | `@role_required(Admin)` & `is_staff=False` | 2× `ACCESS_DENIED` (Dashboard); redirect `/admin/` tidak masuk `SecurityEvent` | **Ya (Dashboard) / Parsial** | **PASS** | Medium |
| **G2-VERIFY** | Admin toggle aktif akun & reset rate limit IP | `POST /users/<id>/toggle/`, `/reset-ratelimit/` | `HTTP 302` sukses | `@role_required(Admin)` + `log_event()` | `ADMIN_USER_UPDATED` (2×) & `ADMIN_SECURITY_OVERRIDE` (1×) | **Ya (Gap G2 Tertutup)** | **PASS** | Info |
| **E1** | Akses `/settings/` pasca `POST /logout/` | `POST /logout/` -> `GET /settings/` | `HTTP 302` ke `/login/?next=/settings/` | `auth_logout()` + `@login_required` | `LOGOUT[SUCCESS]` tercatat; redirect `302` tidak tercatat | **Parsial** | **PASS** | Low |
| **E2** | Replay cookie `sessionid` lama pasca-logout | `GET /settings/` + cookie lama | `HTTP 302` ke `/login/` | Row sesi terhapus di `django_session` | App: tidak ada; DBMS: `SELECT django_session` pasca-`DELETE` | **Tidak di App / Ya di DBMS** | **PASS** | Medium |
| **E3** | Kirim cookie `sessionid` palsu (`forged...`) | `GET /dashboard/admin/` | `HTTP 302` ke `/login/` | Session lookup gagal -> `AnonymousUser` | App: tidak ada | **Tidak di App** | **PASS** | Low |
| **F1** | `CREATE`/`INSERT`/`SELECT` `uji_audit_tmp` & `catalog_product` | PostgreSQL `TrailGear_auth` | `psql exit=0`, query sukses | `log_statement=all` | PostgreSQL Log: `LOG: statement: CREATE/INSERT/SELECT ...` | **Ya** (DBMS) | **PASS** | Info |
| **F2** | `DROP TABLE uji_audit_tmp` & `DELETE accounts_securityevent` (`role_kasir_db`) | PostgreSQL `TrailGear_auth` | `DROP` dummy sukses; `DELETE` ditolak | `REVOKE DELETE` + `log_statement=all` | PostgreSQL Log: `DROP TABLE` + `ERROR: permission denied` | **Ya** (DBMS) | **PASS** | Critical |
| **F3** | Login gagal langsung (`psql -U normal_user` password salah) | PostgreSQL `127.0.0.1:5432` | `FATAL: password authentication failed` | `scram-sha-256` + `log_connections=on` | PostgreSQL Log: `FATAL: password authentication failed` + detail `pg_hba.conf` | **Ya** (DBMS) | **PASS** | High |

### 4.2 Rekonstruksi Korelasi Serangan Berantai 6 Tahap (`IP = 198.51.100.77`)

Dengan menggabungkan **Log Aplikasi** (`accounts_securityevent` + `logs/security.log`) dan **Log DBMS PostgreSQL** (`log_statement = 'all'`), seluruh 6 tahap serangan dapat direkonstruksi kronologis:

| Tahap | Sumber Log | Aktor / DB User | Event / Statement yang Tercatat | Kesimpulan Forensik |
| :---: | :--- | :--- | :--- | :--- |
| **1** | App DB + `security.log` | `anonymous` (`198.51.100.77`) | 3× `LOGIN_FAILED` (`identifier='m8_attacker'`) | Attacker menebak password `m8_attacker` sebanyak 3 kali. |
| **2** | App DB + `security.log` | `m8_attacker` (`user_id=6`) | `LOGIN_SUCCESS` (`user_id=6`) | Attacker berhasil masuk; IP yang sama mengaitkan 3 kegagalan Tahap 1 ke pelaku ini. |
| **3** | App DB + `security.log` | `m8_attacker` | 2× `ACCESS_DENIED` (`/dashboard/cashier/`, `/dashboard/admin/security/`) | Attacker mencoba eskalasi hak akses ke area Kasir & Admin -> diblokir `403`. |
| **4** | App DB + `security.log` | `m8_attacker` | 3× `ACCESS_DENIED` (`order_detail`, `customer_cancel IDOR`, `/confirm/`) | Attacker mencoba IDOR baca/batal/konfirmasi pesanan korban -> diblokir `403`. |
| **5** | **DBMS PostgreSQL** *(App blind spot)* | `tg_user@TrailGear_auth` | `LOG: statement: SELECT COUNT(*) FROM "catalog_product" ... LIKE UPPER('%'' OR 1=1 --%')` | Probing SQLi pada katalog publik yang tidak dicatat di `SecurityEvent` tetap tertangkap di log DBMS tepat di antara Tahap 4 dan 6. |
| **6a** | App DB + `security.log` + DBMS | `m8_attacker` / `tg_user` | `LOGOUT` (`user_id=6`) + `DELETE FROM "django_session" WHERE session_key IN (...)` | Attacker keluar dari sesi; Django menghapus sesi dari DB. |
| **6b** | **DBMS PostgreSQL** *(App blind spot)* | `tg_user@TrailGear_auth` | `LOG: statement: SELECT "django_session" ... WHERE session_key = '<key_lama>'` (beberapa ms setelah `DELETE`) | Membuktikan adanya percobaan *session replay* dengan cookie lama sesaat setelah logout (`HTTP 302`). |

---

## BAB V ANALISIS KEAMANAN & KESIMPULAN

### 5.1 Jawaban Pertanyaan Analisis Keamanan Modul VIII

1. **Apa perbedaan *General Log* dan *Audit Log*?**
   - ***General Log*** (padanan PostgreSQL: `log_statement = 'all'`) merekam seluruh aktivitas dan query mentah tanpa filter — termasuk query `SELECT` rutin — sehingga volumenya besar, membebani I/O & penyimpanan, dan lebih tepat dipakai sementara saat investigasi atau praktikum.
   - ***Audit Log*** (di TrailGear: `accounts_securityevent`, `catalog_inventory_log`, dan PostgreSQL `log_statement = 'mod'/'ddl'`) merekam peristiwa bernilai keamanan secara selektif, terstruktur, dan berorientasi akuntabilitas (siapa aktor, role, IP, status `BLOCKED`/`FAILURE`, serta objek terdampak) sehingga cepat dipakai untuk deteksi serangan dan kepatuhan.
2. **Mengapa logging penting dalam keamanan database?**
   - Memberikan visibilitas penuh (*visibility*) terhadap aktivitas pengguna dan aplikasi, akuntabilitas (*non-repudiation* — membuktikan siapa mengubah atau mengakses data apa dan kapan), deteksi dini intrusi, serta bukti forensik digital pasca-insiden.
3. **Bagaimana log membantu mendeteksi serangan?**
   - Dengan membaca pola anomali lintas lapisan: lonjakan `LOGIN_FAILED` / `RATE_LIMIT_LOGIN` / `FATAL: password authentication failed` menandakan *brute-force*; rentetan `ACCESS_DENIED` pada endpoint kasir/admin/order menandakan *privilege abuse* atau *IDOR*; kemunculan string `' OR 1=1 --` pada `LOGIN_FAILED` atau SQL log menandakan *SQLi probing*; `MAKER_CHECKER_VIOLATION` menandakan upaya *fraud* internal; dan `DROP TABLE` / `ERROR: permission denied` di log DBMS menandakan upaya penghancuran data atau penghapusan jejak audit.
4. **Apa risiko jika logging tidak diaktifkan?**
   - Serangan berjalan tanpa terdeteksi (*silent compromise*), organisasi tidak mengetahui data apa yang dicuri atau diubah, rekonstruksi insiden forensik gagal (*zero evidence*), serta melanggar standar kepatuhan keamanan informasi (seperti ISO 27001 / NIST AU).

### 5.2 Analisis Keamanan Spesifik TrailGear

- **Serangan yang berhasil dideteksi:** Brute-force & distributed lockout (`A1`), user enumeration (`A2`), login akun nonaktif/terkunci (`A3`), privilege abuse direct URL (`B1–B3`), SQLi login (`C1`), IDOR read/write (`D1–D2`), Maker–Checker (`D3`), manipulasi akun/rate-limit oleh Admin (`G2-VERIFY`), kegagalan CSRF (`logs/security.log`), serta seluruh aktivitas DBMS (`F1–F3`).
- **Serangan yang belum terdeteksi di log aplikasi (`accounts_securityevent`):** Probing SQLi/XSS pada halaman publik `/products/?q=` (`C2`, `C3`), *session replay* & *forged cookie* (`E2`, `E3`), dan redirect `302` ke `/admin/login/` (`D4`). Seluruhnya tetap diblokir/di-escape oleh kontrol keamanan dan terlihat pada log DBMS ketika `log_statement = 'all'` aktif.
- **Kecukupan log untuk *incident reconstruction*:** Sangat memadai — kombinasi log aplikasi dan log DBMS mampu merekonstruksi 6/6 tahap serangan berantai hingga tingkat milidetik.
- **Pemeriksaan data sensitif di log:**
  - Di **Log Aplikasi (`accounts_securityevent` & `logs/security.log`)**: **tidak ada** password plaintext, hash password, token CSRF, maupun `sessionid`.
  - Di **Log DBMS PostgreSQL (`log_statement = 'all'`)**: query ORM penuh ikut mencatat **hash password PBKDF2** saat `UPDATE accounts_user` dan **`session_key`** pada query `django_session`. Meskipun bukan password plaintext, temuan ini menegaskan bahwa akses baca berkas log PostgreSQL wajib dibatasi ketat hanya untuk Administrator OS/DBA, dan di produksi `log_statement` harus diturunkan dari `'all'` ke `'mod'` atau `'ddl'`.

### 5.3 Ringkasan Penyesuaian MySQL ke PostgreSQL 18

| Langkah Modul (MySQL) | Padanan PostgreSQL 18 pada TrailGear |
| :--- | :--- |
| `mysql -u root -p` | `psql -h 127.0.0.1 -U postgres -d TrailGear_auth` |
| `SHOW VARIABLES LIKE 'general_log';` | `SHOW logging_collector; SHOW log_statement; SHOW log_connections;` |
| `SET GLOBAL general_log = 'ON';` | `ALTER SYSTEM SET logging_collector = 'on'; ALTER SYSTEM SET log_statement = 'all';` + restart `pg_ctl.exe` |
| `SHOW VARIABLES LIKE 'general_log_file';` | `SHOW data_directory; SHOW log_directory; SELECT pg_current_logfile();` |
| `INSTALL PLUGIN audit_log SONAME 'audit_log.so';` | PostgreSQL Native Audit Parameters (`log_statement`, `log_connections`, `log_disconnections`, `log_line_prefix`) + Application Audit Trail (`accounts_securityevent`, `catalog_inventory_log`) *(ekstensi `pgaudit` tidak tersedia pada bundle EnterpriseDB Windows)* |
| `cat` / `tail -f /var/lib/mysql/hostname.log` | PowerShell `Get-Content <file_log> -Tail 50` dan `Select-String -Path <file_log> -Pattern "..."` |

### 5.4 Tabel Indikator Keberhasilan Modul VIII

| No | Indikator Keberhasilan Modul VIII | Bukti / Langkah Terkait | Hasil |
| :-: | :--- | :--- | :---: |
| 1 | Mengaktifkan logging pada database | Langkah 2 (Gambar 5–8) | **Berhasil** |
| 2 | Menjalankan aktivitas user pada database | Langkah 10 (Gambar 25–27) | **Berhasil** |
| 3 | Log berhasil merekam aktivitas | Langkah 3, 11.3–11.6 (Gambar 9–10, 29–32) | **Berhasil** |
| 4 | Mampu membaca dan memahami log | Langkah 11.2–11.6 (Gambar 28–32) | **Berhasil** |
| 5 | Mampu mengidentifikasi aktivitas mencurigakan | Langkah 5–11 & Bab IV (Gambar 12–31) | **Berhasil** |
| 6 | Menyimpulkan fungsi audit trail | Bab V (Analisis Keamanan & Kesimpulan) | **Terpenuhi** |

### 5.5 Kesimpulan & Rekomendasi

- **Kesimpulan:** Pengaktifan audit logging PostgreSQL 18 (`logging_collector=on`, `log_statement=all`, `log_connections=on`, `log_disconnections=on`, `log_line_prefix='%m [%p] %q%u@%d %r '`) yang dipadukan dengan audit trail aplikasi TrailGear (`accounts_securityevent`, `logs/security.log`, `catalog_inventory_log`) serta penutupan gap audit aksi Admin (`ADMIN_USER_UPDATED`, `ADMIN_SECURITY_OVERRIDE`) dan CSRF berhasil memenuhi seluruh 6 indikator Modul VIII. Sebanyak **20/20 skenario uji** berstatus **PASS** pada sisi kontrol keamanan, dan **6/6 tahap serangan berantai** berhasil direkonstruksi secara akurat lintas lapisan aplikasi dan DBMS.
- **Rekomendasi Lanjutan:**
  1. Turunkan `log_statement` dari `'all'` menjadi `'mod'` pasca-praktikum untuk menghemat penyimpanan dan menghindari pencatatan query `SELECT django_session` berulang di log DBMS.
  2. Batasi izin ACL folder `D:\Apps\PostgreSQL18\data\log\` hanya untuk akun Administrator/PostgreSQL.
  3. Pada deployment produksi, aktifkan web-server *access log* (Nginx/Caddy) di depan Django guna menangkap aktivitas *reconnaissance* pada endpoint publik (`C2`/`C3`).
