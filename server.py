import os
import socket
import threading
import time

SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
VIDEO_PORT = 20000
AUDIO_PORT = 20001
BUFFER_SIZE = 65536
CLIENT_TIMEOUT = 30


def cleanup_clients(clients, stop_event):
    while True:
        if stop_event.wait(10):
            return
        now = time.time()
        with clients["lock"]:
            expired = [
                addr for addr, last_seen in clients["addresses"].items()
                if now - last_seen >= CLIENT_TIMEOUT
            ]
            for addr in expired:
                del clients["addresses"][addr]


def handle_clients(sock, clients, buffer_size, stop_event):
    while not stop_event.is_set():
        try:
            data, sender_addr = sock.recvfrom(buffer_size)
        except socket.timeout:
            continue
        except OSError as error:
            if not stop_event.is_set():
                print(f"Socket receive error: {error}")
            return

        with clients["lock"]:
            clients["addresses"][sender_addr] = time.time()
            recipients = [
                addr for addr in clients["addresses"] if addr != sender_addr
            ]
        for recipient in recipients:
            try:
                sock.sendto(data, recipient)
            except OSError as error:
                print(f"Socket send error: {error}")


def main():
    stop_event = threading.Event()
    video_clients = {"addresses": {}, "lock": threading.Lock()}
    audio_clients = {"addresses": {}, "lock": threading.Lock()}
    video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    audio_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        video_sock.bind((SERVER_HOST, VIDEO_PORT))
        audio_sock.bind((SERVER_HOST, AUDIO_PORT))
        video_sock.settimeout(0.5)
        audio_sock.settimeout(0.5)
        print(
            f"Server running on {SERVER_HOST}, "
            f"video:{VIDEO_PORT}, audio:{AUDIO_PORT}"
        )

        threads = [
            threading.Thread(
                target=handle_clients,
                args=(video_sock, video_clients, BUFFER_SIZE, stop_event),
                daemon=True,
            ),
            threading.Thread(
                target=handle_clients,
                args=(audio_sock, audio_clients, 4096 * 2, stop_event),
                daemon=True,
            ),
            threading.Thread(
                target=cleanup_clients, args=(video_clients, stop_event), daemon=True
            ),
            threading.Thread(
                target=cleanup_clients, args=(audio_clients, stop_event), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()

        try:
            while not stop_event.wait(1):
                pass
        except KeyboardInterrupt:
            print("Server stopping")
    finally:
        stop_event.set()
        video_sock.close()
        audio_sock.close()


if __name__ == "__main__":
    main()
