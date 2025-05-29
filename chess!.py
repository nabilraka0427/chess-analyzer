import os
import threading
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import chess
import chess.engine

# ===== CONFIG ====
STOCKFISH_PATH = 'E:/Semester 4/OS/stockfish-android-armv8'
IMAGE_DIR = os.path.join(os.path.dirname("E:/Semester 4/OS/images"), 'images')
LOG_FILE = os.path.join(os.path.dirname("E:/Semester 4/OS"), 'chess_analyzer.log')
DEPTH_DEFAULT = 15
TILE_SIZE = 80  # size square
MARGIN = 40     # margin for notations
BAR_WIDTH = 20  # width of evaluation bar
THEME = 'clam'

# ===== Logging =====
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# ===== Utilities =====
def square_to_xy(sq):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    x = MARGIN + file * TILE_SIZE
    y = MARGIN + (7 - rank) * TILE_SIZE
    return x, y

# ===== Main App =====
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
            page.place(x=0, y=0, relwidth=1, relheight=1)
        self.show_frame('HomePage')

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def show_frame(self, name):
        page = self.frames[name]
        page.tkraise()
        if name == 'GamePage':
            page.refresh()

    def on_close(self):
        if 'GamePage' in self.frames:
            self.frames['GamePage'].cleanup()
        self.destroy()

# ===== Home Page =====
class HomePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        chess_logo = Image.open(os.path.join(IMAGE_DIR, 'chess_logo.png')).resize((100, 100), Image.LANCZOS)
        #glasses_logo = Image.open(os.path.join(IMAGE_DIR, 'glasses_logo.png')).resize((100, 100), Image.LANCZOS)
        self.chess_logo = ImageTk.PhotoImage(chess_logo)
        #self.glasses_logo = ImageTk.PhotoImage(glasses_logo)

        ttk.Label(self, image=self.chess_logo).pack(pady=10)
        #ttk.Label(self, image=self.glasses_logo).pack(pady=10)
        ttk.Label(self, text='Chess Analyzer', font=('Arial', 32)).pack(pady=40)
        ttk.Button(self, text='Play', command=lambda: controller.show_frame('GamePage')).pack(pady=20)

# ===== Game Page =====
class GamePage(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.board = chess.Board()
        self.move_history = []
        self.classifications = []
        self.best_moves = []
        self.last_played_move = None
        self.analysis_thread = None
        self.is_closing = False
        self.redo_stack = []

        self._init_engine()
        self._load_images()
        self._create_ui()

    def _init_engine(self):
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        except Exception as e:
            messagebox.showerror('Engine Error', str(e))
            self.engine = None

    def _load_images(self):
        self.piece_images = {}
        for fname in os.listdir(IMAGE_DIR):
            if fname.lower().endswith('.png') and 'logo' not in fname:
                key = fname.split('.')[0]
                img = Image.open(os.path.join(IMAGE_DIR, fname)).resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
                self.piece_images[key] = ImageTk.PhotoImage(img)

    def _create_ui(self):
        self.bar = tk.Canvas(self, width=BAR_WIDTH, bg='gray90')
        self.bar.pack(side='left', fill='y', padx=(10, 0), pady=10)

        board_px = TILE_SIZE * 8 + MARGIN * 2
        self.canvas = tk.Canvas(self, width=board_px, height=board_px, bg='white')
        self.canvas.pack(side='left', padx=10, pady=10)
        self.canvas.bind('<Button-1>', self.on_click)

        history_frame = ttk.Frame(self)
        history_frame.pack(side='left', fill='both', expand=True, padx=(10, 20), pady=10)

        self.history = tk.Text(history_frame, width=40, height=20, font=('Courier', 12), bg='white', wrap='word')
        self.history.pack(side='left', fill='both', expand=True)

        scrollbar = ttk.Scrollbar(history_frame, orient='vertical', command=self.history.yview)
        scrollbar.pack(side='right', fill='y')
        self.history.config(yscrollcommand=scrollbar.set, state='disabled')

        for cls, color in [("Best", "blue"), ("Excellent", "green"), ("Good", "green"), ("Inaccuracy", "yellow"), ("Mistake", "orange"), ("Blunder", "red")]:
            self.history.tag_config(cls, foreground=color)

        self.status = ttk.Label(self, text='Ready', font=('Arial', 14))
        self.status.pack(side='bottom', fill='x')

        button_frame = ttk.Frame(self)
        button_frame.pack(side='bottom', fill='x', pady=10)
        ttk.Button(button_frame, text='Undo', command=self.undo_move).pack(side='left', padx=5)
        ttk.Button(button_frame, text='Redo', command=self.redo_move).pack(side='left', padx=5)
        ttk.Button(button_frame, text='Back to Home', command=lambda: self.controller.show_frame('HomePage')).pack(side='left', padx=5)

        rec_frame = ttk.Frame(self)
        rec_frame.pack(side='bottom', fill='x', pady=5)
        self.recommendation = ttk.Label(rec_frame, text='Recommended: None', font=('Arial', 12))
        self.recommendation.pack(side='left', padx=10)

    def refresh(self):
        self._draw_board()
        self._analyze()

    def _draw_board(self):
        self.canvas.delete('all')
        c1, c2 = '#F0D9B5', '#B58863'
        for r in range(8):
            for f in range(8):
                x = MARGIN + f * TILE_SIZE
                y = MARGIN + r * TILE_SIZE
                color = c1 if (r + f) % 2 == 0 else c2
                self.canvas.create_rectangle(x, y, x + TILE_SIZE, y + TILE_SIZE, fill=color)

        # Menambahkan notasi di setiap pinggir papan dengan warna hitam
        for i in range(8):
            # Notasi rank di sisi kiri
            y = MARGIN + i * TILE_SIZE + TILE_SIZE / 2
            self.canvas.create_text(MARGIN / 2, y, text=str(8 - i), font=('Arial', 12), fill='black')
            
            # Notasi rank di sisi kanan
            self.canvas.create_text(MARGIN + 8 * TILE_SIZE + MARGIN / 2, y, text=str(8 - i), font=('Arial', 12), fill='black')
            
            # Notasi file di sisi bawah
            x = MARGIN + i * TILE_SIZE + TILE_SIZE / 2
            self.canvas.create_text(x, MARGIN + 8 * TILE_SIZE + 10, text=chr(ord('a') + i), font=('Arial', 12), fill='black')
            
            # Notasi file di sisi atas
            self.canvas.create_text(x, MARGIN / 2, text=chr(ord('a') + i), font=('Arial', 12), fill='black')

        for sq, piece in self.board.piece_map().items():
            x, y = square_to_xy(sq)
            key = ('w' if piece.symbol().isupper() else 'b') + piece.symbol().upper()
            self.canvas.create_image(x, y, anchor='nw', image=self.piece_images[key])

        if hasattr(self, 'selected') and self.selected is not None:
            for mv in self.board.legal_moves:
                if mv.from_square == self.selected:
                    tx, ty = square_to_xy(mv.to_square)
                    self.canvas.create_oval(
                        tx + TILE_SIZE * 0.2, ty + TILE_SIZE * 0.2,
                        tx + TILE_SIZE * 0.8, ty + TILE_SIZE * 0.8,
                        outline='blue', width=2
                    )

        if self.best_moves:
            mv = self.best_moves[0]
            fx, fy = square_to_xy(mv.from_square)
            tx, ty = square_to_xy(mv.to_square)
            self.canvas.create_line(
                fx + TILE_SIZE / 2, fy + TILE_SIZE / 2,
                tx + TILE_SIZE / 2, ty + TILE_SIZE / 2,
                arrow=tk.LAST, width=3, fill='blue'
            )

    def _draw_bar(self, score):
        self.bar.delete('all')
        height = TILE_SIZE * 8 + MARGIN * 2
        mid = height / 2
        val = max(-1000, min(1000, score))
        length = (val / 1000) * (height / 2)
        if length > 0:
            self.bar.create_rectangle(0, mid - length, BAR_WIDTH, mid, fill='#FFFFFF', outline='#000000')
        else:
            self.bar.create_rectangle(0, mid, BAR_WIDTH, mid - length, fill='#000000', outline='#FFFFFF')
        self.bar.create_line(0, mid, BAR_WIDTH, mid, fill='red', width=2)

    def _analyze(self):
        if self.is_closing or not self.engine or (self.analysis_thread and self.analysis_thread.is_alive()):
            return

        def work():
            try:
                if self.is_closing:
                    return
                info = self.engine.analyse(self.board, chess.engine.Limit(depth=DEPTH_DEFAULT), multipv=2)
                score = info[0]['score'].white().score(mate_score=10000)
                self.best_moves = [info[0]['pv'][0]]

                if self.last_played_move:
                    cls = classify(self.last_played_move, info, self.board, score)
                    self.classifications.append(cls)
                    self.move_history.append(self.last_played_move)
                    self.last_played_move = None

                if not self.is_closing:
                    self.after(0, lambda: [
                        self._draw_bar(score),
                        self._draw_board(),
                        self._update_history(),
                        self._update_recommendation()
                    ])

                if self.board.is_checkmate():
                    self.after(0, self.show_checkmate_popup)

            except Exception as e:
                logging.error('Analysis failed: %s', e)
                self.after(0, lambda: self.status.config(text=f"Analysis Error: {str(e)}"))

        self.analysis_thread = threading.Thread(target=work, daemon=True)
        self.analysis_thread.start()

    def show_checkmate_popup(self):
        result = messagebox.askquestion("Checkmate", "Checkmate! Do you want to try again?", icon='warning')
        if result == 'yes':
            self.board = chess.Board()
            self.move_history = []
            self.classifications = []
            self.best_moves = []
            self.last_played_move = None
            self.redo_stack = []
            self.refresh()
        else:
            self.controller.show_frame('HomePage')

    def _update_history(self):
        self.history.config(state='normal')
        self.history.delete('1.0', 'end')
        temp_board = chess.Board()
        move_number = 1
        for i in range(0, len(self.move_history), 2):
            white_move = self.move_history[i]
            white_san = temp_board.san(white_move)
            white_cls = self.classifications[i]
            temp_board.push(white_move)
            self.history.insert('end', f"{move_number}. ", None)
            self.history.insert('end', white_san, white_cls)
            self.history.insert('end', " ", None)
            if i + 1 < len(self.move_history):
                black_move = self.move_history[i + 1]
                black_san = temp_board.san(black_move)
                black_cls = self.classifications[i + 1]
                temp_board.push(black_move)
                self.history.insert('end', black_san, black_cls)
                self.history.insert('end', " ", None)
            move_number += 1
        self.history.config(state='disabled')

    def _update_recommendation(self):
        if self.best_moves:
            temp_board = self.board.copy()
            best_san = temp_board.san(self.best_moves[0])
            self.recommendation.config(text=f"Recommended: {best_san}")
        else:
            self.recommendation.config(text="Recommended: None")

    def on_click(self, event):
        fx, fy = event.x, event.y
        file = (fx - MARGIN) // TILE_SIZE
        rank = 7 - ((fy - MARGIN) // TILE_SIZE)
        if not (0 <= file < 8 and 0 <= rank < 8):
            return
        sq = chess.square(file, rank)
        if not hasattr(self, 'selected') or self.selected is None:
            if self.board.piece_at(sq) and self.board.color_at(sq) == self.board.turn:
                self.selected = sq
            self._draw_board()
            return
        mv = chess.Move(self.selected, sq)
        if mv not in self.board.legal_moves:
            for legal_mv in self.board.legal_moves:
                if legal_mv.from_square == self.selected and legal_mv.to_square == sq:
                    mv = legal_mv
                    break
        if mv in self.board.legal_moves:
            self.board.push(mv)
            self.last_played_move = mv
            self.redo_stack = []
            self._draw_board()
            self._analyze()
        else:
            self.selected = None
            self._draw_board()

    def undo_move(self):
        if self.board.move_stack:
            last_move = self.board.pop()
            self.redo_stack.append(last_move)
            if self.move_history:
                self.move_history.pop()
            if self.classifications:
                self.classifications.pop()
            self.best_moves = []
            self.last_played_move = None
            self._draw_board()
            self._analyze()

    def redo_move(self):
        if self.redo_stack:
            move = self.redo_stack.pop()
            self.board.push(move)
            self.last_played_move = move
            self._draw_board()
            self._analyze()

    def cleanup(self):
        self.is_closing = True
        if self.engine:
            try:
                self.engine.quit()
            except Exception as e:
                logging.error('Engine cleanup failed: %s', e)
        if self.analysis_thread and self.analysis_thread.is_alive():
            self.analysis_thread.join(timeout=1.0)

# ===== Helpers =====
def classify(move, analysis_info, board, current_score):
    best_move = analysis_info[0]['pv'][0]
    best_score = analysis_info[0]['score'].white().score(mate_score=10000)
    if move == best_move:
        return "Best"
    played_score = None
    if len(analysis_info) > 1 and analysis_info[1]['pv'][0] == move:
        played_score = analysis_info[1]['score'].white().score(mate_score=10000)
    if played_score is None:
        played_score = best_score - 300 if board.turn == chess.WHITE else best_score + 300

    temp_board = board.copy()
    temp_board.pop()
    if temp_board.turn == chess.WHITE:
        cp_loss = best_score - played_score
    else:
        cp_loss = played_score - best_score

    if cp_loss <= 10:
        return "Excellent"
    elif cp_loss <= 50:
        return "Good"
    elif cp_loss <= 100:
        return "Inaccuracy"
    elif cp_loss <= 300:
        return "Mistake"
    else:
        return "Blunder"

def get_color(cls):
    return {
        "Best": "blue",
        "Excellent": "green",
        "Good": "green",
        "Inaccuracy": "yellow",
        "Mistake": "orange",
        "Blunder": "red"
    }.get(cls, "black")

# ===== Run =====
if __name__ == '__main__':
    app = MainApp()
    app.mainloop()