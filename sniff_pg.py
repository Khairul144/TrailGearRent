"""TCP Packet Sniffer (Padanan Windows untuk: tcpdump -i lo -A -s0 port 5432).
Meneruskan dan merekam seluruh payload paket antara client (127.0.0.1:15432)
dan server PostgreSQL (127.0.0.1:5432) ke file log ASCII untuk analisis sniffing.
"""

import datetime
import socket
import sys
import threading

OUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "capture_no_ssl.txt"
LISTEN_PORT = 15432
TARGET_HOST, TARGET_PORT = "127.0.0.1", 5432


def to_ascii_dump(data: bytes) -> str:
    """Seperti tcpdump -A: karakter printable ditampilkan apa adanya, byte lain diganti '.'."""
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data)


def pipe(src, dst, direction, f, lock):
    try:
        while True:
            data = src.recv(65535)
            if not data:
                break
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            ascii_view = to_ascii_dump(data)
            line = f"[{ts}] {direction} ({len(data)} bytes): {ascii_view}\n"
            with lock:
                f.write(line)
                f.flush()
                print(line.strip())
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def main():
    lock = threading.Lock()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", LISTEN_PORT))
        srv.listen(5)
        print(
            f"[SNIFFER AKTIF] Merekam trafik 127.0.0.1:{LISTEN_PORT} -> "
            f"{TARGET_HOST}:{TARGET_PORT} ke '{OUT_FILE}'"
        )
        print("Tekan Ctrl+C setelah selesai menangkap paket...\n")
        try:
            while True:
                client, _ = srv.accept()
                target = socket.create_connection((TARGET_HOST, TARGET_PORT))
                threading.Thread(
                    target=pipe, args=(client, target, "CLIENT->PG", f, lock), daemon=True
                ).start()
                threading.Thread(
                    target=pipe, args=(target, client, "PG->CLIENT", f, lock), daemon=True
                ).start()
        except KeyboardInterrupt:
            print(f"\n[SNIFFER BERHENTI] Hasil rekaman tersimpan di: {OUT_FILE}")
        finally:
            srv.close()


if __name__ == "__main__":
    main()
