# Phase 1 — Temporary Account Lockout (TrailGear)

**Lingkup:** hanya account lockout. Rate limiting, RBAC, password policy, session, dan arsitektur login **tidak diubah**.

---

## 1. Files changed

| File | Perubahan |
|---|---|
| `accounts/models.py` | 2 field baru pada `User`; properti `is_locked`; metode `register_failed_login()` dan `reset_login_lock()`; event `ACCOUNT_LOCKED` |
| `accounts/views.py` | Integrasi lockout ke `login_view` (cek lock sebelum `authenticate`), konstanta `LOCKED_LOGIN_ERROR`, increment atomik saat credential gagal, reset saat sukses |
| `accounts/admin.py` | Kolom `failed_login_attempts` & `locked_until` di list, readonly fieldset "Keamanan" |
| `config/settings.py` | `ACCOUNT_LOCKOUT_THRESHOLD = 10`, `ACCOUNT_LOCKOUT_DURATION = 15` (menit, bisa di-override `.env`) |
| `accounts/tests.py` | 11 test baru `AccountLockoutTests` |
| `.env.example` | contoh dua variabel lockout |
| `accounts/migrations/0005_*.py` | migration field + alter choices (dibuat `makemigrations`, bukan manual) |

## 2. Database changes

```python
failed_login_attempts = models.PositiveIntegerField(default=0)
locked_until          = models.DateTimeField(null=True, blank=True)
```

Migration: `accounts.0005_user_failed_login_attempts_user_locked_until_and_more` → applied.
Tidak ada reset/flush/drop; user lama tetap utuh (default `0` dan `NULL` → bisa login normal).

## 3. Account lockout behaviour (final flow)

```
POST /login/
   │
   ├─ rate limit (5 gagal/10 menit per IP+identitas)  → 429 bila lewat
   │
   ├─ cari akun dari identifier (username/email)
   │     └─ akun ADA & is_locked?  → tolak (pesan "Akun sementara tidak dapat digunakan…")
   │                                  password TIDAK diverifikasi, lock TIDAK diperpanjang
   │
   ├─ authenticate()
   │     ├─ sukses → reset counter + locked_until → login + redirect sesuai role
   │     └─ gagal  → failed_login_attempts += 1 (atomik, F())
   │                 └─ >= 10 → locked_until = now + 15 menit + event ACCOUNT_LOCKED
   │
   └─ pesan generik "Username/email atau password tidak valid."
```

Properti tambahan: `locked_until` lewat dari `now` → `is_locked` False, akun bisa login lagi.

**Anti race-condition:** increment memakai `User.objects.filter(pk=...).update(failed_login_attempts=F(...) + 1)` di dalam `transaction.atomic()`, lalu `refresh_from_db`, sehingga dua request paralel tidak saling menimpa.

**Anti lock-extension:** percobaan saat akun sudah terkunci tidak memanggil `register_failed_login()`, jadi `locked_until` tidak bergeser.

## 4. Security logging

Event baru: `ACCOUNT_LOCKED` (status `BLOCKED`), dicatat saat lock baru terjadi:

```
event=ACCOUNT_LOCKED status=BLOCKED ip=127.0.0.1 user_id=… desc=threshold=10 durasi=15menit
```

Percobaan login saat akun terkunci dicatat sebagai `LOGIN_FAILED` dengan deskripsi `Akun terkunci sementara; login ditolak.` (tanpa timestamp internal, tanpa counter).

Tidak di-log: password, password_confirmation, session id, CSRF token, secret key.

## 5. Tests

| Kelompok | Jumlah |
|---|---|
| Existing unit test (`accounts.tests`) | 84 |
| Test baru `AccountLockoutTests` | 11 |
| **Total** | **95** |

Test baru: increment, reset saat sukses, threshold 10, password benar saat locked, password salah saat locked (tanpa perpanjangan), lock expired, rate limiting tetap 429, pesan generik tanpa kebocoran, pesan locked aman, event `ACCOUNT_LOCKED` tanpa data sensitif, user lama tetap bisa login.

Hasil: `AccountLockoutTests` → **11/11 PASS**.

## 6. Regression

Lihat bagian "Regression result" pada laporan chat (dijalankan `manage.py test accounts`).

## 7. Manual HTTP test

Dijalankan terhadap `http://127.0.0.1:8000/login/` dengan user `httplock_demo`:

| Langkah | Hasil |
|---|---|
| Login normal | HTTP 302 → `/` · counter 0 |
| Gagal 1–9 | HTTP 200 · counter naik 1→9 · belum locked |
| Gagal ke-10 | HTTP 200 · counter 10 · `locked_until` terisi (+15 menit) · event `ACCOUNT_LOCKED` |
| Password benar saat locked | HTTP 200 · "Akun sementara tidak dapat digunakan. Silakan coba lagi nanti." · tidak ada redirect/sesi |
| Password salah saat locked | HTTP 200 · pesan sama · `locked_until` **tidak berubah** |
| Lock expired (dimundurkan 1 detik) | HTTP 302 → `/` · counter 0 · `locked_until` NULL |
| Rate limit (1 IP, 6 percobaan beruntun) | `1..5: 200`, `6: 429` (tidak berubah) |

Catatan metode: karena rate limit 5/10 menit per IP akan menutup jalur sebelum 10 kegagalan, cache rate-limit dibersihkan di antara percobaan lockout (mensimulasikan IP/jendela waktu berbeda). Rate limiting sendiri tidak diubah.

## 8. Potential issues

1. **Threshold 10 vs rate limit 5 per IP** — dari satu IP, 10 kegagalan tidak mungkin tercapai dalam satu jendela 10 menit; lockout efektif untuk penyerang yang memakai banyak IP atau setelah jendela rate limit lewat. Ini konsekuensi konfigurasi yang diminta (keduanya dipertahankan), bukan bug.
2. **Counter tidak direset saat lock** — mengikuti spesifikasi (counter tetap 10). Setelah lock expired, satu kegagalan baru (counter 11) langsung mengunci ulang. Jika diinginkan perilaku "mulai dari nol setelah lock", perlu reset counter saat lock terjadi.
3. **Pesan "Akun sementara tidak dapat digunakan" hanya muncul untuk akun yang benar-benar terkunci** — penyerang bisa menyimpulkan sebuah identifier memiliki akun terkunci. Ini konsekuensi pesan yang diminta spesifikasi; pesan generik tetap dipakai untuk credential failure.
4. **Rate limit tetap di-bump saat akun terkunci** agar endpoint tidak bisa dispam tanpa batas; efeknya percobaan berulang saat locked bisa berubah menjadi 429 sebelum pesan locked muncul.
