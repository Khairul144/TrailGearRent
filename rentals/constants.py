"""Konstanta informasi pembayaran TrailGear Rent."""

# Nomor WhatsApp resmi (format internasional tanpa "+").
WHATSAPP_NUMBER = "6287812000155"

BANK_ACCOUNTS = [
    {
        "method": "TRANSFER_BCA",
        "bank": "BCA",
        "number": "029-xxxxxxx",
        "holder": "TrailGear Rent",
    },
    {
        "method": "TRANSFER_MANDIRI",
        "bank": "Mandiri",
        "number": "138-xxxxxxx",
        "holder": "TrailGear Rent",
    },
    {
        "method": "TRANSFER_BNI",
        "bank": "BNI",
        "number": "012-xxxxxxx",
        "holder": "TrailGear Rent",
    },
    {
        "method": "QRIS",
        "bank": "QRIS",
        "number": "Scan QRIS di kasir",
        "holder": "TrailGear Rent",
    },
    {
        "method": "CASH",
        "bank": "Tunai",
        "number": "Bayar langsung di toko",
        "holder": "Kasir TrailGear",
    },
]

PAYMENT_INSTRUCTIONS = [
    "Transfer sesuai nominal total biaya sewa (tanpa deposit).",
    "Cantumkan kode booking pada berita/keterangan transfer.",
    "Unggah foto/screenshot bukti transfer (JPG, PNG, WEBP, atau PDF, maks. 5 MB).",
    "Kasir memverifikasi bukti, lalu status pesanan berubah menjadi Dikonfirmasi.",
    "Jaminan sewa berupa KTP asli fisik yang wajib dibawa saat pengambilan alat.",
]
