import os
import threading
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import chess
import chess.engine
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

# ===== Konfigurasi =====
STOCKFISH_PATH = '/opt/homebrew/bin/stockfish'  # Sesuaikan dengan lokasi Stockfish di sistem Anda
IMAGE_DIR = os.path.join(os.path.dirname(__file__), 'images')  # Direktori gambar bidak catur
LOG_FILE = os.path.join(os.path.dirname(__file__), 'chess_analyzer.log')
DEPTH_DEFAULT = 15  # Kedalaman analisis default
DEPTH_ACCURACY = 10  # Kedalaman untuk analisis akurasi
TILE_SIZE = 80  # Ukuran kotak papan catur
MARGIN = 40  # Margin papan
BAR_WIDTH = 20  # Lebar bar evaluasi
THEME = 'clam'  # Tema Tkinter

# ===== Logging =====
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# ===== Fungsi Utilitas =====
def square_to_xy(sq):
    """Konversi indeks kotak catur ke koordinat x, y."""
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    x = MARGIN + file * TILE_SIZE
    y = MARGIN + (7 - rank) * TILE_SIZE
    return x, y

# Ambang batas klasifikasi (kerugian centipawn)
CLASSIFICATION_THRESHOLDS = {
    'Best': 0,
    'Excellent': 10,
    'Good': 50,
    'Inaccuracy': 100,
    'Mistake': 300,
    'Blunder': float('inf')
}

# ===== Aplikasi Utama =====
class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        board_px = TILE_SIZE * 8 + MARGIN * 2
        total_w = BAR_WIDTH + board_px + 300
        total_h = board_px + 100
        self.geometry(f"{total_w}x{total_h}")
        self.title('Chess Analyzer')
        ttk.Style(self).theme_use(THEME)

        container = ttk.Frame(self)
        container.pack(fill='both', expand=True)
        self.frames = {}
        for F in (HomePage, GamePage):
            page = F(container, self)
            self.frames[F.__name__] = page
            page.place(relwidth=1, relheight=1)
        self.show_frame('HomePage')
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def show_frame(self, name):
        """Menampilkan halaman tertentu."""
        page = self.frames[name]
        page.tkraise()
        if name == 'GamePage': page.refresh()

    def on_close(self):
        """Menangani penutupan aplikasi."""
        if 'GamePage' in self.frames: self.frames['GamePage'].cleanup()
        self.destroy()

# ===== Halaman Beranda =====
class HomePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        l1 = Image.open(os.path.join(IMAGE_DIR, 'chess_logo.png')).resize((100, 100), Image.LANCZOS)
        l2 = Image.open(os.path.join(IMAGE_DIR, 'glasses_logo.png')).resize((100, 100), Image.LANCZOS)
        self.logo1 = ImageTk.PhotoImage(l1)
        self.logo2 = ImageTk.PhotoImage(l2)
        ttk.Label(self, image=self.logo1).pack(pady=10)
        ttk.Label(self, image=self.logo2).pack(pady=10)
        ttk.Label(self, text='Chess Analyzer', font=('Arial', 32)).pack(pady=40)
        ttk.Button(self, text='Play', command=lambda: controller.show_frame('GamePage')).pack(pady=20)

# ===== Halaman Permainan =====
class GamePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.board = chess.Board()
        self.move_history = []
        self.classifications = []
        self.accuracies = []
        self.best_moves = []
        self.last_move = None
        self.analysis_thread = None
        self.is_closing = False
        self.redo_stack = []
        self.analysis_before_score = 0  # Skor awal netral (0)
        self.evaluation_scores = [0]  # Mulai dengan evaluasi netral

        self._init_engine()
        self._load_images()
        self._create_ui()

    def _init_engine(self):
        """Inisialisasi engine Stockfish."""
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        except Exception as e:
            messagebox.showerror('Engine Error', str(e))
            self.engine = None

    def _load_images(self):
        """Memuat gambar bidak catur."""
        self.piece_images = {}
        for f in os.listdir(IMAGE_DIR):
            if f.endswith('.png') and 'logo' not in f:
                key = f.split('.')[0]
                img = Image.open(os.path.join(IMAGE_DIR, f)).resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
                self.piece_images[key] = ImageTk.PhotoImage(img)

    def _create_ui(self):
        """Membuat antarmuka pengguna."""
        self.bar = tk.Canvas(self, width=BAR_WIDTH, bg='gray90')
        self.bar.pack(side='left', fill='y', padx=(10, 0), pady=10)
        px = TILE_SIZE * 8 + MARGIN * 2
        self.canvas = tk.Canvas(self, width=px, height=px, bg='white')
        self.canvas.pack(side='left', padx=10, pady=10)
        self.canvas.bind('<Button-1>', self.on_click)
        hf = ttk.Frame(self)
        hf.pack(side='left', fill='both', expand=True, padx=(10, 20), pady=10)
        self.history = tk.Text(hf, width=40, height=20, font=('Courier', 12), bg='white', wrap='word')
        self.history.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(hf, orient='vertical', command=self.history.yview)
        sb.pack(side='right', fill='y')
        self.history.config(yscrollcommand=sb.set, state='disabled')
        for cls in CLASSIFICATION_THRESHOLDS:
            color = 'blue' if cls == 'Best' else 'green' if cls == 'Excellent' else 'lightgreen' if cls == 'Good' else 'yellow' if cls == 'Inaccuracy' else 'orange' if cls == 'Mistake' else 'red'
            self.history.tag_config(cls, foreground=color)
        self.status = ttk.Label(self, text='Ready', font=('Arial', 14))
        self.status.pack(side='bottom', fill='x')
        bf = ttk.Frame(self)
        bf.pack(side='bottom', fill='x', pady=10)
        ttk.Button(bf, text='Undo', command=self.undo_move).pack(side='left', padx=5)
        ttk.Button(bf, text='Redo', command=self.redo_move).pack(side='left', padx=5)
        ttk.Button(bf, text='Home', command=lambda: self.controller.show_frame('HomePage')).pack(side='left', padx=5)

        # Grafik untuk skor evaluasi
        self.fig, self.ax = plt.subplots(figsize=(4, 3))
        self.ax.set_title("Skor Evaluasi")
        self.ax.set_xlabel("Nomor Langkah")
        self.ax.set_ylabel("Centipawn (Perspektif Putih)")
        self.graph_canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.graph_canvas.get_tk_widget().pack(side='right', fill='both', expand=True)

    def refresh(self):
        """Memperbarui tampilan papan dan analisis."""
        self._draw_board()
        self._analyze()

    def _draw_board(self):
        """Menggambar papan catur."""
        self.canvas.delete('all')
        c1, c2 = '#F0D9B5', '#B58863'
        for r in range(8):
            for f in range(8):
                x, y = MARGIN + f * TILE_SIZE, MARGIN + r * TILE_SIZE
                col = c1 if (r + f) % 2 == 0 else c2
                self.canvas.create_rectangle(x, y, x + TILE_SIZE, y + TILE_SIZE, fill=col)
        for i in range(8):
            y = MARGIN + i * TILE_SIZE + TILE_SIZE / 2
            self.canvas.create_text(MARGIN / 2, y, text=str(8 - i))
            self.canvas.create_text(MARGIN + 8 * TILE_SIZE + MARGIN / 2, y, text=str(8 - i))
            x = MARGIN + i * TILE_SIZE + TILE_SIZE / 2
            self.canvas.create_text(x, MARGIN + 8 * TILE_SIZE + 10, text=chr(97 + i))
            self.canvas.create_text(x, MARGIN / 2, text=chr(97 + i))
        for sq, p in self.board.piece_map().items():
            x, y = square_to_xy(sq)
            key = ('w' if p.symbol().isupper() else 'b') + p.symbol().upper()
            self.canvas.create_image(x, y, anchor='nw', image=self.piece_images[key])
        if hasattr(self, 'selected') and self.selected is not None:
            for mv in self.board.legal_moves:
                if mv.from_square == self.selected:
                    tx, ty = square_to_xy(mv.to_square)
                    self.canvas.create_oval(tx + TILE_SIZE * 0.2, ty + TILE_SIZE * 0.2, tx + TILE_SIZE * 0.8, ty + TILE_SIZE * 0.8, outline='blue', width=2)
        if self.best_moves:
            mv = self.best_moves[0]
            fx, fy = square_to_xy(mv.from_square)
            tx, ty = square_to_xy(mv.to_square)
            self.canvas.create_line(fx + TILE_SIZE / 2, fy + TILE_SIZE / 2, tx + TILE_SIZE / 2, ty + TILE_SIZE / 2, arrow=tk.LAST, width=3, fill='blue')

    def _draw_bar(self, score):
        """Menggambar bar evaluasi."""
        self.bar.delete('all')
        h = TILE_SIZE * 8 + MARGIN * 2
        mid = h / 2
        val = max(-1000, min(1000, score))
        ln = (val / 1000) * (h / 2)
        if ln > 0:
            self.bar.create_rectangle(0, mid - ln, BAR_WIDTH, mid, fill='#FFF', outline='')
        else:
            self.bar.create_rectangle(0, mid, BAR_WIDTH, mid - ln, fill='#000', outline='')
        self.bar.create_line(0, mid, BAR_WIDTH, mid, fill='red', width=2)

    def _analyze(self):
        """Menganalisis posisi saat ini dengan Stockfish."""
        if self.is_closing or not self.engine or (self.analysis_thread and self.analysis_thread.is_alive()):
            return
        def work():
            try:
                if self.is_closing:
                    return
                info = self.engine.analyse(self.board, chess.engine.Limit(depth=DEPTH_DEFAULT), multipv=2)
                score = info[0]['score'].white().score(mate_score=10000)
                self.best_moves = [info[0]['pv'][0]]
                if self.last_move is not None:
                    before = self.analysis_before_score
                    after_info = self.engine.analyse(self.board, chess.engine.Limit(depth=DEPTH_ACCURACY))
                    after = after_info['score'].white().score(mate_score=10000)
                    color = not self.board.turn
                    cls, accuracy = classify_and_accuracy(self.last_move, before, after, color)
                    self.classifications.append(cls)
                    self.accuracies.append(accuracy)
                    self.move_history.append(self.last_move)
                    self.last_move = None
                self.analysis_before_score = score
                self.evaluation_scores.append(score)
                if not self.is_closing:
                    self.after(0, lambda: [self._draw_bar(score), self._draw_board(), self._update_history(), self._update_graph()])
                if self.board.is_checkmate():
                    self.after(0, self.show_checkmate_popup)
            except Exception as e:
                logging.error('Analysis failed: %s', e)
                self.after(0, lambda: self.status.config(text=f"Error: {e}"))
        self.analysis_thread = threading.Thread(target=work, daemon=True)
        self.analysis_thread.start()

    def on_click(self, event):
        """Menangani klik pada papan catur."""
        fx, fy = event.x, event.y
        file = (fx - MARGIN) // TILE_SIZE
        rank = 7 - ((fy - MARGIN) // TILE_SIZE)
        if not (0 <= file < 8 and 0 <= rank < 8):
            return
        sq = chess.square(int(file), int(rank))
        if not hasattr(self, 'selected') or self.selected is None:
            if self.board.piece_at(sq) and self.board.color_at(sq) == self.board.turn:
                self.selected = sq
            self._draw_board()
            return
        mv = chess.Move(self.selected, sq)
        if mv not in self.board.legal_moves:
            for lm in self.board.legal_moves:
                if lm.from_square == self.selected and lm.to_square == sq:
                    mv = lm
                    break
        if mv in self.board.legal_moves:
            self.board.push(mv)
            self.last_move = mv
            self.selected = None
            self._draw_board()
            self._analyze()
        else:
            self.selected = None
            self._draw_board()

    def undo_move(self):
        """Membatalkan langkah terakhir."""
        if self.board.move_stack:
            last = self.board.pop()
            self.redo_stack.append(last)
            if self.move_history:
                self.move_history.pop()
                self.classifications.pop()
                self.accuracies.pop()
            self.best_moves = []
            self.last_move = None
            self._draw_board()
            self._analyze()

    def redo_move(self):
        """Mengulang langkah yang dibatalkan."""
        if self.redo_stack:
            mv = self.redo_stack.pop()
            self.board.push(mv)
            self.last_move = mv
            self._draw_board()
            self._analyze()

    def _update_history(self):
        """Memperbarui riwayat langkah."""
        self.history.config(state='normal')
        self.history.delete('1.0', 'end')
        temp = chess.Board()
        num = 1
        for i, mv in enumerate(self.move_history):
            san = temp.san(mv)
            cls = self.classifications[i]
            acc = self.accuracies[i]
            temp.push(mv)
            if i % 2 == 0:
                self.history.insert('end', f"{num}. ")
            self.history.insert('end', f"{san} ({cls}, {acc:.1f}%)", cls)
            self.history.insert('end', ' ')
            if i % 2:
                num += 1
        self.history.config(state='disabled')

    def _update_graph(self):
        """Memperbarui grafik skor evaluasi sesuai standar chess.com."""
        self.ax.clear()
        self.ax.set_title("Skor Evaluasi")
        self.ax.set_xlabel("Nomor Langkah")
        self.ax.set_ylabel("Centipawn (Perspektif Putih)")
        moves = list(range(len(self.evaluation_scores)))
        plot_scores = [max(-1000, min(1000, s)) for s in self.evaluation_scores]

        # Garis tren abu-abu
        self.ax.plot(moves, plot_scores, color='gray', linestyle='-', linewidth=1)
        
        # Warna untuk titik-titik berdasarkan klasifikasi (mirip chess.com)
        colors = ['black']  # Posisi awal
        for cls in self.classifications:
            if cls == 'Best':
                colors.append('blue')
            elif cls == 'Excellent':
                colors.append('green')
            elif cls == 'Good':
                colors.append('lightgreen')
            elif cls == 'Inaccuracy':
                colors.append('yellow')
            elif cls == 'Mistake':
                colors.append('orange')
            else:  # Blunder
                colors.append('red')
        
        # Gambar titik-titik dengan warna sesuai klasifikasi
        for i, (x, y, c) in enumerate(zip(moves, plot_scores, colors)):
            self.ax.scatter(x, y, color=c, zorder=5)
        
        # Fill areas untuk menunjukkan keunggulan
        self.ax.fill_between(moves, plot_scores, 0, where=np.array(plot_scores) > 0, color='lightgray', alpha=0.5)
        self.ax.fill_between(moves, plot_scores, 0, where=np.array(plot_scores) < 0, color='darkgray', alpha=0.5)
        self.ax.set_ylim(-1000, 1000)
        
        self.graph_canvas.draw()

    def show_checkmate_popup(self):
        """Menampilkan pop-up skakmat di tengah papan."""
        popup = tk.Toplevel(self)
        popup.title("Skakmat")
        popup.geometry("200x100")  # Ukuran sedang
        # Posisi tengah papan
        board_x = self.canvas.winfo_rootx() + self.canvas.winfo_width() // 2 - 100
        board_y = self.canvas.winfo_rooty() + self.canvas.winfo_height() // 2 - 50
        popup.geometry(f"+{board_x}+{board_y}")
        ttk.Label(popup, text="Skakmat!", font=('Arial', 16)).pack(pady=10)
        ttk.Button(popup, text="Kembali ke Beranda", command=lambda: [popup.destroy(), self.controller.show_frame('HomePage')]).pack(pady=10)
        popup.transient(self)
        popup.grab_set()
        self.wait_window(popup)

    def cleanup(self):
        """Membersihkan sumber daya saat keluar."""
        self.is_closing = True
        if self.engine:
            self.engine.quit()
        if self.analysis_thread and self.analysis_thread.is_alive():
            self.analysis_thread.join(1)

# ===== Fungsi Pembantu =====
def classify_and_accuracy(move, before, after, color):
    """Mengklasifikasikan langkah dan menghitung akurasi."""
    if color == chess.WHITE:
        cp_loss = before - after
    else:
        cp_loss = after - before
    cp_loss = max(0, cp_loss)
    if cp_loss <= 0:
        cls = 'Best'
        accuracy = 100
    elif cp_loss <= 10:
        cls = 'Excellent'
        accuracy = 98
    elif cp_loss <= 50:
        cls = 'Good'
        accuracy = 95
    elif cp_loss <= 100:
        cls = 'Inaccuracy'
        accuracy = 80
    elif cp_loss <= 300:
        cls = 'Mistake'
        accuracy = 60
    else:
        cls = 'Blunder'
        accuracy = 40
    return cls, accuracy

if __name__ == '__main__':
    app = MainApp()
    app.mainloop()
