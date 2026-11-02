import tkinter as tk
from tkinter import ttk, messagebox
import socket
import cv2
import pyaudio
import numpy as np
import threading
import time
from threading import Lock
from PIL import Image, ImageTk
from collections import deque

VIDEO_PORT = 20000
AUDIO_PORT = 20001
BUFFER_SIZE = 65536
AUDIO_CHUNKS = 4
CHUNK = 1024

class SmoothZoomClientOptimized:
    def __init__(self, master):
        self.master = master
        master.title("Smooth Zoom Client - Optimized")
        self.master.configure(bg="#2C3E50")
        self.is_running = False
        self.is_stopped = False
        self.video_labels = {}
        self.pending_frames = {}
        self.pending_frames_lock = Lock()
        self.hand_raised = {}
        self.clients_muted = {}
        self.clients_hide_video = {}
        self.mute_all = False
        self.mute_me = False
        self.hide_self = False
        self.stop_video = False

        # --- Top Frame ---
        top = tk.Frame(master, bg="#2C3E50")
        top.pack(fill=tk.X, pady=5)
        tk.Label(top, text="My ID:", fg="white", bg="#2C3E50").pack(side=tk.LEFT)
        self.id_entry = tk.Entry(top, width=3)
        self.id_entry.pack(side=tk.LEFT, padx=5)
        tk.Label(top, text="Server IP:", fg="white", bg="#2C3E50").pack(side=tk.LEFT)
        self.server_entry = tk.Entry(top)
        self.server_entry.pack(side=tk.LEFT, padx=5)

        # --- Buttons ---
        btns = tk.Frame(master, bg="#2C3E50")
        btns.pack(fill=tk.X, pady=5)
        self.start_btn = ttk.Button(btns, text="Start", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=3)
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=3)
        self.mute_me_btn = ttk.Button(btns, text="Mute Me", command=self.toggle_mute_me, state=tk.DISABLED)
        self.mute_me_btn.pack(side=tk.LEFT, padx=3)
        self.stop_video_btn = ttk.Button(btns, text="Stop Video", command=self.toggle_stop_video, state=tk.DISABLED)
        self.stop_video_btn.pack(side=tk.LEFT, padx=3)
        self.raise_hand_btn = ttk.Button(btns, text="Raise Hand", command=self.toggle_raise_hand, state=tk.DISABLED)
        self.raise_hand_btn.pack(side=tk.LEFT, padx=3)

        # --- Main Frame & Canvas ---
        self.main_frame = tk.Frame(master, bg="#34495E")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.main_frame, width=600, height=600, bg="#34495E", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#34495E")
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        # --- Client Sidebar ---
        self.client_frame = tk.Frame(self.main_frame, width=200, bg="#2C3E50")
        self.client_frame.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Label(self.client_frame, text="Clients", bg="#2C3E50", fg="white", font=("Arial",12,"bold")).pack(pady=5)

        # --- Sockets ---
        self.video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.video_sock.bind(('0.0.0.0', 0))
        self.video_sock.settimeout(0.5)
        self.audio_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.audio_sock.bind(('0.0.0.0', 0))
        self.audio_sock.settimeout(0.5)

        # --- Audio ---
        self.p_audio = pyaudio.PyAudio()
        self.stream_out = self.p_audio.open(format=pyaudio.paInt16, channels=1, rate=44100, output=True, frames_per_buffer=CHUNK)
        self.stream_in = None
        self.audio_buffer = deque(maxlen=AUDIO_CHUNKS)

        # --- Camera ---
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("Error", "Cannot open camera")
        self.master.after(30, self.process_pending_frames)

    # --- Toggle Buttons ---
    def toggle_mute_me(self):
        self.mute_me = not self.mute_me
        self.mute_me_btn.config(text="Unmute Me" if self.mute_me else "Mute Me")

    def toggle_stop_video(self):
        self.stop_video = not self.stop_video
        self.stop_video_btn.config(text="Start Video" if self.stop_video else "Stop Video")

    def toggle_raise_hand(self):
        self.hand_raised[self.my_id] = not self.hand_raised.get(self.my_id, False)
        self.raise_hand_btn.config(text="Lower Hand" if self.hand_raised[self.my_id] else "Raise Hand")

    # --- Start/Stop ---
    def start(self):
        self.my_id = self.id_entry.get().strip()
        if len(self.my_id) != 1:
            messagebox.showerror("Error", "ID must be a single character")
            return
        self.server_ip = self.server_entry.get().strip()
        if not self.server_ip:
            messagebox.showerror("Error", "Enter the server IP address")
            return
        try:
            socket.getaddrinfo(self.server_ip, VIDEO_PORT, type=socket.SOCK_DGRAM)
        except socket.gaierror as error:
            messagebox.showerror("Error", f"Invalid server address: {error}")
            return
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.mute_me_btn.config(state=tk.NORMAL)
        self.stop_video_btn.config(state=tk.NORMAL)
        self.raise_hand_btn.config(state=tk.NORMAL)

        self.threads = [
            threading.Thread(target=self.send_video, daemon=True),
            threading.Thread(target=self.send_audio, daemon=True),
            threading.Thread(target=self.receive_video, daemon=True),
            threading.Thread(target=self.receive_audio, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def stop(self):
        if self.is_stopped:
            return
        self.is_stopped = True
        self.is_running = False
        self.video_sock.close()
        self.audio_sock.close()
        self.cap.release()
        for thread in getattr(self, "threads", []):
            thread.join(timeout=1)
        if self.stream_out.is_active():
            self.stream_out.stop_stream()
        self.stream_out.close()
        self.p_audio.terminate()
        self.master.destroy()

    # --- Video ---
    def send_video(self):
        while self.is_running:
            if self.stop_video:
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if not ret: continue
            frame = cv2.resize(frame, (280,180))
            if self.hand_raised.get(self.my_id, False):
                cv2.putText(frame, '✋', (10,20), cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2)
            _, buff = cv2.imencode('.jpg', frame,[cv2.IMWRITE_JPEG_QUALITY,50])
            packet = self.my_id.encode() + buff.tobytes()
            try: self.video_sock.sendto(packet, (self.server_ip, VIDEO_PORT))
            except Exception as e: print(f"Video send error: {e}")
            time.sleep(0.25)

    def receive_video(self):
        while self.is_running:
            try:
                data, _ = self.video_sock.recvfrom(BUFFER_SIZE)
                if not data:
                    continue
                sender_id = data[0:1].decode("utf-8")
                if sender_id == self.my_id: continue
                frame = cv2.imdecode(np.frombuffer(data[1:], np.uint8), cv2.IMREAD_COLOR)
                if frame is None: continue
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self.pending_frames_lock:
                    self.pending_frames[sender_id] = frame
            except socket.timeout:
                continue
            except OSError as error:
                if self.is_running:
                    print(f"Video receive error: {error}")
                return
            except Exception as error:
                print(f"Video receive error: {error}")

    def process_pending_frames(self):
        with self.pending_frames_lock:
            frames = self.pending_frames.copy()
            self.pending_frames.clear()
        for sender_id, frame in frames.items():
            image = ImageTk.PhotoImage(image=Image.fromarray(frame))
            if sender_id not in self.video_labels:
                label = tk.Label(
                    self.scrollable_frame,
                    text=f"User {sender_id}",
                    compound=tk.TOP,
                    bg="#34495E",
                    fg="white",
                )
                self.video_labels[sender_id] = label
                self.hand_raised[sender_id] = False
                self.clients_muted[sender_id] = False
                self.clients_hide_video[sender_id] = False
                self.add_client_control(sender_id)
                self.update_grid()
            label = self.video_labels[sender_id]
            label.imgtk = image
            if not self.clients_hide_video[sender_id]:
                label.config(image=image)
        if self.master.winfo_exists():
            self.master.after(30, self.process_pending_frames)

    # --- Audio ---
    def send_audio(self):
        try:
            self.stream_in = self.p_audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=44100,
                input=True,
                frames_per_buffer=CHUNK,
            )
            while self.is_running:
                if self.mute_me:
                    time.sleep(0.05)
                    continue
                audio_data = self.stream_in.read(
                    CHUNK, exception_on_overflow=False
                )
                packet = self.my_id.encode() + audio_data
                self.audio_sock.sendto(packet, (self.server_ip, AUDIO_PORT))
        except Exception as error:
            if self.is_running:
                print(f"Audio send error: {error}")
        finally:
            if self.stream_in is not None:
                if self.stream_in.is_active():
                    self.stream_in.stop_stream()
                self.stream_in.close()
                self.stream_in = None

    def receive_audio(self):
        while self.is_running:
            try:
                data, _ = self.audio_sock.recvfrom(CHUNK*2 + 1)
                if not data:
                    continue
                sender_id = data[0:1].decode("utf-8")
                if sender_id == self.my_id or self.mute_all: continue
                if self.clients_muted.get(sender_id, False): continue
                self.audio_buffer.append(data[1:])
                while self.audio_buffer:
                    chunk = self.audio_buffer.popleft()
                    self.stream_out.write(chunk)
            except socket.timeout:
                continue
            except OSError as error:
                if self.is_running:
                    print(f"Audio receive error: {error}")
                return
            except Exception as error:
                print(f"Audio receive error: {error}")

    # --- Client Controls ---
    def add_client_control(self, client_id):
        frame = tk.Frame(self.client_frame, bg="#2C3E50")
        frame.pack(pady=2)
        tk.Label(frame,text=client_id,bg="#2C3E50",fg="white").pack(side=tk.LEFT)
        btn_mute = ttk.Button(frame,text="Mute",command=lambda cid=client_id:self.toggle_client_mute(cid))
        btn_mute.pack(side=tk.LEFT,padx=2)
        btn_hide = ttk.Button(frame,text="Hide",command=lambda cid=client_id:self.toggle_client_hide(cid))
        btn_hide.pack(side=tk.LEFT,padx=2)

    def toggle_client_mute(self,cid):
        self.clients_muted[cid] = not self.clients_muted[cid]

    def toggle_client_hide(self,cid):
        self.clients_hide_video[cid] = not self.clients_hide_video[cid]
        label = self.video_labels[cid]
        if self.clients_hide_video[cid]: label.config(image=None)
        else: label.config(image=label.imgtk)

    def update_grid(self):
        columns = min(3,len(self.video_labels))
        for i,label in enumerate(self.video_labels.values()):
            row = i//columns
            col = i%columns
            label.grid(row=row,column=col,padx=5,pady=5)


# --- Main ---
if __name__ == "__main__":
    root = tk.Tk()
    app = SmoothZoomClientOptimized(root)
    root.protocol("WM_DELETE_WINDOW", app.stop)
    root.mainloop()
