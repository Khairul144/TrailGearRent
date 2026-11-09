"""
Validasi berkas bukti pembayaran — murni standard library.

Tidak memakai Pillow/python-magic. Pertahanan berlapis:
1. Whitelist ekstensi (anti webshell) + tolak ekstensi ganda.
2. Batas ukuran (anti DoS): 1 byte s/d 5 MB.
3. Magic bytes: isi berkas harus benar-benar JPEG/PNG/WebP/PDF.
4. Nama file selalu diganti UUID (lihat models.payment_proof_upload_path),
   sehingga nama asli dari browser tidak pernah menyentuh filesystem.
"""

import os
import uuid
from django.core.exceptions import ValidationError
from django.utils import timezone

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
HEADER_SIZE = 32

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DANGEROUS_EXTENSIONS = {
    ".php", ".php3", ".php4", ".php5", ".phtml", ".phar",
    ".py", ".pyc", ".rb", ".pl", ".sh", ".bash",
    ".exe", ".dll", ".bat", ".cmd", ".com", ".msi", ".scr",
    ".html", ".htm", ".xhtml", ".svg", ".js", ".mjs", ".jsp",
    ".asp", ".aspx", ".cgi", ".htaccess", ".ini", ".sql",
}

def _extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def validate_original_name(filename: str) -> str:
    """Periksa nama asli: satu ekstensi saja, tanpa path traversal.

    Nama asli tidak pernah dipakai untuk menyimpan berkas (selalu UUID), jadi
    karakter unicode/spasi diperbolehkan; yang ditolak hanya pemisah path,
    karakter kontrol, dan ekstensi ganda.
    """
    filename = (filename or "").strip()
    if not filename:
        raise ValidationError("Berkas tidak memiliki nama.")

    # Bytes NUL / kontrol pada nama file -> indikasi manipulasi.
    if any(ch in filename for ch in ("\x00", "\n", "\r")):
        raise ValidationError("Nama berkas mengandung karakter tidak valid.")

    # Path traversal (Windows & POSIX) tidak pernah diterima.
    if "/" in filename or "\\" in filename:
        raise ValidationError("Nama berkas tidak boleh mengandung folder.")

    base = os.path.basename(filename)
    parts = base.split(".")
    # "bukti.php.jpg" -> 3 bagian; tolak ekstensi ganda sepenuhnya.
    if len(parts) != 2 or not parts[0].strip():
        raise ValidationError(
            "Nama berkas tidak boleh memiliki ekstensi ganda."
        )

    ext = "." + parts[1].lower()
    if ext in DANGEROUS_EXTENSIONS:
        raise ValidationError("Jenis berkas ini tidak diizinkan.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            "Format berkas harus JPG, JPEG, PNG, WEBP, atau PDF."
        )
    return ext


def _matches_magic_bytes(ext: str, header: bytes) -> bool:
    if ext in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return (
            len(header) >= 12
            and header[0:4] == b"RIFF"
            and header[8:12] == b"WEBP"
        )
    if ext == ".pdf":
        return header.startswith(b"%PDF-")
    return False


MAGIC_LABEL = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WebP",
    ".pdf": "PDF",
}


def validate_payment_proof(uploaded_file) -> str:
    """Validasi lengkap sebuah UploadedFile. Mengembalikan ekstensi aman."""
    if uploaded_file is None:
        raise ValidationError("Berkas bukti pembayaran wajib diunggah.")

    ext = validate_original_name(getattr(uploaded_file, "name", ""))

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise ValidationError("Berkas kosong tidak dapat diunggah.")
    if size > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise ValidationError(f"Ukuran berkas maksimal {max_mb} MB.")

    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(HEADER_SIZE)
    finally:
        uploaded_file.seek(0)

    if not isinstance(header, (bytes, bytearray)) or not _matches_magic_bytes(ext, bytes(header)):
        expected = MAGIC_LABEL.get(ext, "yang sesuai")
        raise ValidationError(
            f"Isi berkas bukan {expected} yang valid. Berkas yang di-rename tidak diterima."
        )

    return ext


def payment_proof_upload_path(instance, filename: str) -> str:
    """Path simpan: payment_proofs/<tahun>/<bulan>/<uuid>.<ext>."""
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".bin"
    now = timezone.now()
    return f"payment_proofs/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}"
