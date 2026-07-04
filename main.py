"""
main.py — Muze: Modern Offline Music Player
100% Python standard library  (tkinter + ctypes, no pip required).

Layout
------
  ┌──────────────────────────────────────────────────┐
  │  SIDEBAR (320 px)       │  NOW-PLAYING PANEL      │
  │  • App title + theme    │  • Animated cover art   │
  │  • Open Folder button   │  • Track title/artist   │
  │  • Search box           │  • Seek bar             │
  │  • Track list (canvas)  │  • Playback controls    │
  │                         │  • Volume               │
  └──────────────────────────────────────────────────┘

Audio: Windows MCI via ctypes (MCIPlayer in utils.py)
       Supports MP3, WAV, WMA, M4A, FLAC (native Windows codecs)
"""

from __future__ import annotations

import io
import os
import random
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, ttk
from typing import Optional

# ---------------------------------------------------------------------------
# Import our pure-stdlib utilities
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
from utils import MCIPlayer, format_duration, scan_directory

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
BG_DARK        = "#0D0D1A"
SIDEBAR_BG     = "#111128"
CARD_BG        = "#1A1A35"
BORDER_CLR     = "#252550"
HOVER_BG       = "#1E1E42"
ACTIVE_BG      = "#27275A"

ACCENT         = "#7C3AED"   # vivid purple
ACCENT2        = "#4F46E5"   # indigo
ACCENT_GLOW    = "#A78BFA"   # soft lavender
ACCENT_CYAN    = "#06B6D4"

TEXT_PRIMARY   = "#EEE9FF"
TEXT_SECONDARY = "#8883BB"
TEXT_DIM       = "#5555AA"

BG_LIGHT       = "#EEEEF8"
SIDEBAR_LIGHT  = "#F5F5FF"
CARD_LIGHT     = "#FFFFFF"
BORDER_LIGHT   = "#DDDDF5"
HOVER_LIGHT    = "#E8E8F8"
ACTIVE_LIGHT   = "#D8D8F0"
TEXT_P_LIGHT   = "#1A1A3E"
TEXT_S_LIGHT   = "#5B5B8A"

SIDEBAR_W      = 300
MIN_W, MIN_H   = 860, 620

# Repeat cycle
REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = "off", "all", "one"

# ---------------------------------------------------------------------------
# Pillow-free PNG/JPEG loader — write cover bytes to a temp .png and load
# ---------------------------------------------------------------------------
def _bytes_to_photoimage(raw: bytes) -> Optional[tk.PhotoImage]:
    """
    Load raw image bytes (JPEG or PNG) into a tk.PhotoImage.
    Writes to a temp PNG file using only stdlib (works for PNG natively;
    for JPEG we write a temp file and use tkinter's PPM workaround via
    the Pillow-optional path).
    """
    # Try PIL/Pillow silently (user may have it installed)
    try:
        from PIL import Image, ImageTk  # type: ignore
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGBA")
        img = img.resize((220, 220), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: write to temp file and let tkinter load it
    suffix = ".png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else ".ppm"
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(raw)
        tmp.close()
        photo = tk.PhotoImage(file=tmp.name)
        os.unlink(tmp.name)
        return photo
    except Exception:
        pass
    return None


def _resize_photoimage(ph: tk.PhotoImage, size: int) -> tk.PhotoImage:
    """Scale a PhotoImage to size×size using tkinter's subsample/zoom."""
    w, h = ph.width(), ph.height()
    if w == 0 or h == 0:
        return ph
    # Zoom to at least size×size, then subsample
    factor = max(size / w, size / h)
    zh = max(1, round(h * factor))
    zw = max(1, round(w * factor))
    try:
        ph2 = ph.zoom(round(factor)) if factor > 1 else ph
        sub = max(1, round(max(zw, zh) / size))
        if sub > 1:
            ph2 = ph2.subsample(sub, sub)
        return ph2
    except Exception:
        return ph


# ---------------------------------------------------------------------------
# Rounded rectangle helper for Canvas
# ---------------------------------------------------------------------------
def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r=12, **kw):
    """Draw a rounded rectangle on *canvas*."""
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2,     y1,
        x2,     y1 + r,
        x2,     y2 - r,
        x2,     y2,
        x2 - r, y2,
        x1 + r, y2,
        x1,     y2,
        x1,     y2 - r,
        x1,     y1 + r,
        x1,     y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class MuzeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.is_dark = True

        # Playback state
        self.player = MCIPlayer()
        self.all_tracks: list[dict] = []
        self.filtered_tracks: list[dict] = []
        self.current_index: int = -1
        self.is_playing: bool = False
        self.duration_ms: int = 0
        self.position_ms: int = 0
        self.seek_dragging: bool = False
        self.shuffle_mode: bool = False
        self.repeat_mode: str = REPEAT_OFF
        self.shuffle_order: list[int] = []
        self._position_poll_id = None

        # Loaded PhotoImage references (prevent GC)
        self._cover_photo: Optional[tk.PhotoImage] = None
        self._default_cover_photo: Optional[tk.PhotoImage] = None

        self._setup_window()
        self._load_fonts()
        self._build_ui()
        self._load_default_cover()
        self._schedule_position_poll()

    # -----------------------------------------------------------------------
    # Window setup
    # -----------------------------------------------------------------------
    def _setup_window(self):
        r = self.root
        r.title("Muze — Offline Music Player")
        r.configure(bg=BG_DARK)
        r.minsize(MIN_W, MIN_H)
        # Centre on screen
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w, h = 1100, 700
        r.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        r.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_fonts(self):
        """Pre-resolve font objects used throughout the UI."""
        try:
            self.font_title  = font.Font(family="Segoe UI", size=18, weight="bold")
            self.font_medium = font.Font(family="Segoe UI", size=12, weight="bold")
            self.font_body   = font.Font(family="Segoe UI", size=11)
            self.font_small  = font.Font(family="Segoe UI", size=9)
            self.font_brand  = font.Font(family="Segoe UI", size=16, weight="bold")
            self.font_track  = font.Font(family="Segoe UI", size=11)
            self.font_artist = font.Font(family="Segoe UI", size=9)
        except Exception:
            self.font_title  = font.Font(size=18, weight="bold")
            self.font_medium = font.Font(size=12, weight="bold")
            self.font_body   = font.Font(size=11)
            self.font_small  = font.Font(size=9)
            self.font_brand  = font.Font(size=16, weight="bold")
            self.font_track  = font.Font(size=11)
            self.font_artist = font.Font(size=9)

    # -----------------------------------------------------------------------
    # Build UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        # Root is a horizontal pane
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, minsize=SIDEBAR_W, weight=0)
        self.root.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_player_panel()

    # -----------------------------------------------------------------------
    # SIDEBAR
    # -----------------------------------------------------------------------
    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=SIDEBAR_BG, width=SIDEBAR_W)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(4, weight=1)
        sb.grid_columnconfigure(0, weight=1)
        self.sidebar = sb

        # ---- Header row: brand name + theme toggle ----
        header = tk.Frame(sb, bg=SIDEBAR_BG)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 0))
        header.grid_columnconfigure(0, weight=1)

        brand = tk.Label(header, text="♫  muze", bg=SIDEBAR_BG,
                         fg=ACCENT_GLOW, font=self.font_brand)
        brand.grid(row=0, column=0, sticky="w")

        self.theme_btn = tk.Button(
            header, text="☀", bg=SIDEBAR_BG, fg=TEXT_SECONDARY,
            relief="flat", cursor="hand2", font=self.font_body,
            activebackground=SIDEBAR_BG, activeforeground=TEXT_PRIMARY,
            command=self._toggle_theme, bd=0, padx=4,
        )
        self.theme_btn.grid(row=0, column=1, sticky="e")

        # ---- Open Folder button ----
        self.open_btn = tk.Button(
            sb, text="  ⊕  Open Folder",
            bg=ACCENT, fg="white",
            font=self.font_body,
            relief="flat", cursor="hand2",
            activebackground=ACCENT2, activeforeground="white",
            command=self._pick_folder,
            pady=8,
        )
        self.open_btn.grid(row=1, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._add_hover(self.open_btn, ACCENT2, ACCENT)

        # ---- Search box ----
        search_frame = tk.Frame(sb, bg=CARD_BG, highlightbackground=BORDER_CLR,
                                highlightthickness=1)
        search_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        tk.Label(search_frame, text="⌕", bg=CARD_BG, fg=TEXT_SECONDARY,
                 font=font.Font(size=14)).grid(row=0, column=0, padx=(8, 4))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.search_entry = tk.Entry(
            search_frame, textvariable=self.search_var,
            bg=CARD_BG, fg=TEXT_PRIMARY,
            insertbackground=ACCENT_GLOW,
            relief="flat", font=self.font_body,
            highlightthickness=0,
        )
        self.search_entry.grid(row=0, column=1, sticky="ew", pady=8, padx=(0, 8))
        self.search_entry.insert(0, "")
        # Placeholder
        self.search_entry.bind("<FocusIn>",  self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self._search_placeholder = True
        self.search_entry.insert(0, "Search songs, artists…")
        self.search_entry.config(fg=TEXT_SECONDARY)

        # ---- Track count label ----
        self.count_var = tk.StringVar(value="No folder selected")
        tk.Label(sb, textvariable=self.count_var, bg=SIDEBAR_BG,
                 fg=TEXT_DIM, font=self.font_small, anchor="w"
                 ).grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 2))

        # ---- Separator ----
        sep = tk.Frame(sb, bg=BORDER_CLR, height=1)
        sep.grid(row=3, column=0, sticky="ew", pady=(20, 0))

        # ---- Track list (Canvas + Scrollbar) ----
        list_frame = tk.Frame(sb, bg=SIDEBAR_BG)
        list_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 0))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.track_canvas = tk.Canvas(
            list_frame, bg=SIDEBAR_BG, bd=0, highlightthickness=0,
        )
        self.track_canvas.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(list_frame, orient="vertical",
                               command=self.track_canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.track_canvas.configure(yscrollcommand=scroll.set)

        self.track_inner = tk.Frame(self.track_canvas, bg=SIDEBAR_BG)
        self._track_window = self.track_canvas.create_window(
            (0, 0), window=self.track_inner, anchor="nw"
        )
        self.track_inner.bind("<Configure>", self._on_list_configure)
        self.track_canvas.bind("<Configure>", self._on_canvas_configure)
        self.track_canvas.bind("<MouseWheel>", self._on_mousewheel)

        self.track_inner.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_list_configure(self, e=None):
        self.track_canvas.configure(scrollregion=self.track_canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self.track_canvas.itemconfig(self._track_window, width=e.width)

    def _on_mousewheel(self, e):
        self.track_canvas.yview_scroll(-1 * (e.delta // 120), "units")

    # -----------------------------------------------------------------------
    # NOW-PLAYING PANEL
    # -----------------------------------------------------------------------
    def _build_player_panel(self):
        panel = tk.Frame(self.root, bg=BG_DARK)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(0, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        self.player_panel = panel

        # Vertical layout: cover → info → seek → controls → volume
        inner = tk.Frame(panel, bg=BG_DARK)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.player_inner = inner

        # ---- Cover art ----
        self.cover_frame = tk.Frame(
            inner, bg=ACCENT, width=220, height=220,
        )
        self.cover_frame.pack(pady=(0, 20))
        self.cover_frame.pack_propagate(False)

        self.cover_label = tk.Label(self.cover_frame, bg=ACCENT)
        self.cover_label.place(relx=0.5, rely=0.5, anchor="center")

        # ---- Track title ----
        self.title_var = tk.StringVar(value="Open a folder to start")
        self.title_label = tk.Label(
            inner, textvariable=self.title_var,
            bg=BG_DARK, fg=TEXT_PRIMARY,
            font=self.font_title,
            wraplength=400,
        )
        self.title_label.pack()

        # ---- Artist ----
        self.artist_var = tk.StringVar(value="No track selected")
        self.artist_label = tk.Label(
            inner, textvariable=self.artist_var,
            bg=BG_DARK, fg=ACCENT_GLOW,
            font=self.font_body,
        )
        self.artist_label.pack(pady=(4, 0))

        # ---- Album ----
        self.album_var = tk.StringVar(value="")
        self.album_label = tk.Label(
            inner, textvariable=self.album_var,
            bg=BG_DARK, fg=TEXT_SECONDARY,
            font=self.font_small,
        )
        self.album_label.pack(pady=(2, 16))

        # ---- Seek bar row ----
        seek_row = tk.Frame(inner, bg=BG_DARK)
        seek_row.pack(fill="x", padx=20)

        self.pos_var = tk.StringVar(value="0:00")
        tk.Label(seek_row, textvariable=self.pos_var, bg=BG_DARK,
                 fg=TEXT_SECONDARY, font=self.font_small, width=5
                 ).pack(side="left")

        # ttk slider style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Seek.Horizontal.TScale",
                        troughcolor=BORDER_CLR,
                        sliderthickness=14,
                        sliderrelief="flat",
                        background=ACCENT,
                        borderwidth=0)
        style.configure("Vol.Horizontal.TScale",
                        troughcolor=BORDER_CLR,
                        sliderthickness=12,
                        sliderrelief="flat",
                        background=ACCENT2,
                        borderwidth=0)

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_slider = ttk.Scale(
            seek_row, orient="horizontal", from_=0, to=1000,
            variable=self.seek_var, style="Seek.Horizontal.TScale",
            command=self._on_seek_move,
        )
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.seek_slider.bind("<ButtonPress-1>",   self._on_seek_press)
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)

        self.dur_var = tk.StringVar(value="0:00")
        tk.Label(seek_row, textvariable=self.dur_var, bg=BG_DARK,
                 fg=TEXT_SECONDARY, font=self.font_small, width=5
                 ).pack(side="right")

        # ---- Playback controls ----
        ctrl = tk.Frame(inner, bg=BG_DARK)
        ctrl.pack(pady=(14, 0))

        btn_kw = dict(bg=BG_DARK, relief="flat", cursor="hand2",
                      activebackground=BG_DARK, bd=0, padx=6)

        self.shuffle_btn = tk.Button(
            ctrl, text="⇄", fg=TEXT_SECONDARY,
            font=font.Font(size=16), command=self._toggle_shuffle, **btn_kw,
        )
        self.shuffle_btn.pack(side="left", padx=2)

        self.prev_btn = tk.Button(
            ctrl, text="⏮", fg=TEXT_PRIMARY,
            font=font.Font(size=20), command=self._prev_track, **btn_kw,
        )
        self.prev_btn.pack(side="left", padx=2)

        # Big play/pause button — drawn as a circle
        self.play_canvas = tk.Canvas(
            ctrl, width=60, height=60, bg=BG_DARK,
            bd=0, highlightthickness=0,
        )
        self.play_canvas.pack(side="left", padx=6)
        self._draw_play_button(playing=False)
        self.play_canvas.bind("<Button-1>", self._toggle_play_pause)
        self.play_canvas.configure(cursor="hand2")

        self.next_btn = tk.Button(
            ctrl, text="⏭", fg=TEXT_PRIMARY,
            font=font.Font(size=20), command=self._next_track, **btn_kw,
        )
        self.next_btn.pack(side="left", padx=2)

        self.repeat_btn = tk.Button(
            ctrl, text="↺", fg=TEXT_SECONDARY,
            font=font.Font(size=16), command=self._cycle_repeat, **btn_kw,
        )
        self.repeat_btn.pack(side="left", padx=2)

        # ---- Volume ----
        vol_row = tk.Frame(inner, bg=BG_DARK)
        vol_row.pack(pady=(12, 0))

        self.vol_icon = tk.Label(vol_row, text="🔊", bg=BG_DARK,
                                 fg=TEXT_SECONDARY, font=font.Font(size=13))
        self.vol_icon.pack(side="left")

        self.vol_var = tk.DoubleVar(value=800)  # 0–1000
        self.vol_slider = ttk.Scale(
            vol_row, orient="horizontal", from_=0, to=1000,
            variable=self.vol_var, style="Vol.Horizontal.TScale",
            length=140,
            command=self._on_volume_change,
        )
        self.vol_slider.pack(side="left", padx=8)
        self.player.volume = 0.8

    # -----------------------------------------------------------------------
    # Play button canvas drawing
    # -----------------------------------------------------------------------
    def _draw_play_button(self, playing: bool):
        c = self.play_canvas
        c.delete("all")
        # Outer circle
        c.create_oval(2, 2, 58, 58, fill=ACCENT, outline="", tags="circle")
        if playing:
            # Pause icon: two bars
            c.create_rectangle(20, 18, 26, 42, fill="white", outline="")
            c.create_rectangle(34, 18, 40, 42, fill="white", outline="")
        else:
            # Play icon: triangle
            c.create_polygon(22, 16, 22, 44, 46, 30, fill="white", smooth=False)
        # Hover effect
        c.tag_bind("circle", "<Enter>", lambda e: c.itemconfig("circle", fill=ACCENT2))
        c.tag_bind("circle", "<Leave>", lambda e: c.itemconfig("circle", fill=ACCENT))

    # -----------------------------------------------------------------------
    # Default cover art
    # -----------------------------------------------------------------------
    def _load_default_cover(self):
        cover_path = Path(__file__).parent / "assets" / "default_cover.png"
        if cover_path.exists():
            try:
                ph = tk.PhotoImage(file=str(cover_path))
                # Resize via subsample if larger than 220
                pw, ph_h = ph.width(), ph.height()
                if pw > 220:
                    sub = max(1, pw // 220)
                    ph = ph.subsample(sub, sub)
                self._default_cover_photo = ph
                self.cover_label.configure(image=ph)
                self.cover_label.image = ph
                self.cover_frame.configure(
                    width=220, height=220, bg=BG_DARK,
                    highlightbackground=ACCENT, highlightthickness=0,
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Folder scanning
    # -----------------------------------------------------------------------
    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Select Music Folder")
        if not folder:
            return
        self.count_var.set("Scanning…")
        threading.Thread(target=self._do_scan, args=(folder,), daemon=True).start()

    def _do_scan(self, folder: str):
        tracks = scan_directory(folder)
        # Schedule UI update on main thread
        self.root.after(0, self._on_scan_done, tracks)

    def _on_scan_done(self, tracks: list[dict]):
        self.all_tracks = tracks
        self.filtered_tracks = list(tracks)
        n = len(tracks)
        self.count_var.set(f"{n} track{'s' if n != 1 else ''} found")
        self._render_track_list()

    # -----------------------------------------------------------------------
    # Track list rendering
    # -----------------------------------------------------------------------
    def _render_track_list(self):
        # Destroy previous rows
        for w in self.track_inner.winfo_children():
            w.destroy()

        for idx, track in enumerate(self.filtered_tracks):
            self._add_track_row(idx, track)

        self.track_inner.update_idletasks()
        self._on_list_configure()

    def _add_track_row(self, idx: int, track: dict):
        is_active = (idx == self.current_index)
        row_bg = ACTIVE_BG if is_active else SIDEBAR_BG

        row = tk.Frame(self.track_inner, bg=row_bg, cursor="hand2")
        row.pack(fill="x", padx=0, pady=0)

        # Left accent bar for active
        bar_clr = ACCENT_GLOW if is_active else row_bg
        bar = tk.Frame(row, bg=bar_clr, width=3)
        bar.pack(side="left", fill="y")

        # Thumbnail / mini icon
        thumb_frame = tk.Frame(row, bg=row_bg, width=44, height=44)
        thumb_frame.pack(side="left", padx=(6, 0), pady=6)
        thumb_frame.pack_propagate(False)

        thumb_loaded = False
        if track.get("cover"):
            try:
                ph = _bytes_to_photoimage(track["cover"])
                if ph is None:
                    raise ValueError
                # Resize to 40×40
                if ph.width() > 40:
                    sub = max(1, ph.width() // 40)
                    ph = ph.subsample(sub, sub)
                lbl = tk.Label(thumb_frame, image=ph, bg=row_bg)
                lbl.image = ph  # prevent GC
                lbl.place(relx=0.5, rely=0.5, anchor="center")
                thumb_loaded = True
            except Exception:
                pass

        if not thumb_loaded:
            # Gradient-ish coloured square with note
            c = tk.Canvas(thumb_frame, width=40, height=40,
                          bg=ACCENT, bd=0, highlightthickness=0)
            c.place(relx=0.5, rely=0.5, anchor="center")
            c.create_text(20, 20, text="♫", fill="white",
                          font=font.Font(size=14))

        # Text column
        text_frame = tk.Frame(row, bg=row_bg)
        text_frame.pack(side="left", fill="both", expand=True, padx=8)

        title_fg = ACCENT_GLOW if is_active else TEXT_PRIMARY
        tk.Label(
            text_frame, text=track["title"],
            bg=row_bg, fg=title_fg,
            font=self.font_track, anchor="w",
            wraplength=160,
        ).pack(fill="x")

        tk.Label(
            text_frame, text=track["artist"],
            bg=row_bg, fg=TEXT_SECONDARY,
            font=self.font_artist, anchor="w",
        ).pack(fill="x")

        # Bind click on all children
        for widget in [row, bar, thumb_frame, text_frame] + list(text_frame.winfo_children()):
            widget.bind("<Button-1>", lambda e, i=idx: self._play_track(i))
            widget.bind("<Enter>",    lambda e, r=row, b=bar_clr, a=is_active: self._row_hover(r, a, True))
            widget.bind("<Leave>",    lambda e, r=row, b=bar_clr, a=is_active: self._row_hover(r, a, False))

    def _row_hover(self, row: tk.Frame, is_active: bool, entering: bool):
        if is_active:
            return
        bg = HOVER_BG if entering else SIDEBAR_BG
        row.configure(bg=bg)
        for w in row.winfo_children():
            try:
                w.configure(bg=bg)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Playback
    # -----------------------------------------------------------------------
    def _play_track(self, idx: int):
        if not self.filtered_tracks or idx < 0 or idx >= len(self.filtered_tracks):
            return
        self.current_index = idx
        track = self.filtered_tracks[idx]

        # Open in MCI player
        ok = self.player.open(track["path"])
        if ok:
            self.player.play()
            self.is_playing = True
            self.duration_ms = 0  # will update on first poll
        self._update_now_playing(track)
        self._draw_play_button(playing=self.is_playing)
        self._render_track_list()

    def _toggle_play_pause(self, e=None):
        if self.current_index < 0:
            if self.filtered_tracks:
                self._play_track(0)
            return
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
        else:
            mode = self.player.get_mode()
            if mode == "paused":
                self.player.resume()
            else:
                self.player.play()
            self.is_playing = True
        self._draw_play_button(playing=self.is_playing)

    def _prev_track(self):
        if not self.filtered_tracks:
            return
        # If >3 sec played, restart; else go previous
        if self.position_ms > 3000 and self.current_index >= 0:
            self.player.seek(0)
            return
        idx = self._get_prev_idx()
        self._play_track(idx)

    def _next_track(self):
        if not self.filtered_tracks:
            return
        idx = self._get_next_idx()
        if idx == -1:
            self.player.stop()
            self.is_playing = False
            self._draw_play_button(playing=False)
            return
        self._play_track(idx)

    def _get_next_idx(self) -> int:
        n = len(self.filtered_tracks)
        if n == 0:
            return -1
        if self.shuffle_mode:
            if not self.shuffle_order:
                self._build_shuffle_order()
            try:
                pos = self.shuffle_order.index(self.current_index)
                if pos + 1 < len(self.shuffle_order):
                    return self.shuffle_order[pos + 1]
            except ValueError:
                pass
            if self.repeat_mode == REPEAT_ALL:
                self._build_shuffle_order()
                return self.shuffle_order[0] if self.shuffle_order else -1
            return -1
        else:
            nxt = self.current_index + 1
            if nxt < n:
                return nxt
            if self.repeat_mode == REPEAT_ALL:
                return 0
            return -1

    def _get_prev_idx(self) -> int:
        n = len(self.filtered_tracks)
        if n == 0:
            return 0
        if self.shuffle_mode:
            if not self.shuffle_order:
                self._build_shuffle_order()
            try:
                pos = self.shuffle_order.index(self.current_index)
                return self.shuffle_order[max(0, pos - 1)]
            except ValueError:
                pass
        return max(0, self.current_index - 1)

    def _build_shuffle_order(self):
        order = list(range(len(self.filtered_tracks)))
        random.shuffle(order)
        self.shuffle_order = order

    def _toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        if self.shuffle_mode:
            self._build_shuffle_order()
            self.shuffle_btn.configure(fg=ACCENT_GLOW)
        else:
            self.shuffle_btn.configure(fg=TEXT_SECONDARY)

    def _cycle_repeat(self):
        if self.repeat_mode == REPEAT_OFF:
            self.repeat_mode = REPEAT_ALL
            self.repeat_btn.configure(fg=ACCENT_GLOW, text="↺ all")
        elif self.repeat_mode == REPEAT_ALL:
            self.repeat_mode = REPEAT_ONE
            self.repeat_btn.configure(fg=ACCENT, text="↺ 1")
        else:
            self.repeat_mode = REPEAT_OFF
            self.repeat_btn.configure(fg=TEXT_SECONDARY, text="↺")

    # -----------------------------------------------------------------------
    # Seek bar
    # -----------------------------------------------------------------------
    def _on_seek_press(self, e=None):
        self.seek_dragging = True

    def _on_seek_release(self, e=None):
        if self.duration_ms > 0:
            target_ms = int(self.seek_var.get() / 1000 * self.duration_ms)
            self.player.seek(target_ms)
            if not self.is_playing:
                self.is_playing = True
                self._draw_play_button(playing=True)
        self.seek_dragging = False

    def _on_seek_move(self, val=None):
        if self.seek_dragging and self.duration_ms > 0:
            ms = int(float(val) / 1000 * self.duration_ms)
            self.pos_var.set(format_duration(ms))

    # -----------------------------------------------------------------------
    # Volume
    # -----------------------------------------------------------------------
    def _on_volume_change(self, val=None):
        v = float(val) / 1000.0
        self.player.volume = v
        if v == 0:
            self.vol_icon.configure(text="🔇")
        elif v < 0.4:
            self.vol_icon.configure(text="🔉")
        else:
            self.vol_icon.configure(text="🔊")

    # -----------------------------------------------------------------------
    # Position polling — updates seek slider and time labels
    # -----------------------------------------------------------------------
    def _schedule_position_poll(self):
        self._poll_position()

    def _poll_position(self):
        try:
            if self.is_playing:
                pos = self.player.get_position()
                lng = self.player.get_length()
                mode = self.player.get_mode()

                if lng > 0 and self.duration_ms != lng:
                    self.duration_ms = lng
                    self.dur_var.set(format_duration(lng))

                self.position_ms = pos
                if not self.seek_dragging and lng > 0:
                    self.seek_var.set(pos / lng * 1000)
                    self.pos_var.set(format_duration(pos))

                # Detect natural end of track
                if mode in ("stopped", "") and pos > 0 and lng > 0 and pos >= lng - 500:
                    self.is_playing = False
                    self._draw_play_button(playing=False)
                    if self.repeat_mode == REPEAT_ONE:
                        self.root.after(200, lambda: self._play_track(self.current_index))
                    else:
                        self.root.after(200, self._next_track)
        except Exception:
            pass
        finally:
            self._position_poll_id = self.root.after(500, self._poll_position)

    # -----------------------------------------------------------------------
    # Now Playing display
    # -----------------------------------------------------------------------
    def _update_now_playing(self, track: dict):
        self.title_var.set(track["title"])
        self.artist_var.set(track["artist"])
        album = track["album"] if track["album"] != "Unknown Album" else ""
        self.album_var.set(album)
        self.seek_var.set(0)
        self.pos_var.set("0:00")
        self.dur_var.set("0:00")
        self.duration_ms = 0
        self.position_ms = 0

        # Load cover art
        self._cover_photo = None
        if track.get("cover"):
            ph = _bytes_to_photoimage(track["cover"])
            if ph:
                self._cover_photo = ph
                self.cover_label.configure(image=ph, bg=BG_DARK)
                self.cover_label.image = ph
                self.cover_frame.configure(bg=BG_DARK, highlightthickness=0)
                return
        # Fallback
        if self._default_cover_photo:
            self.cover_label.configure(image=self._default_cover_photo)
            self.cover_label.image = self._default_cover_photo
        else:
            self.cover_label.configure(image="", text="♫",
                                       font=font.Font(size=60), fg=TEXT_PRIMARY)

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------
    def _search_focus_in(self, e=None):
        if self._search_placeholder:
            self.search_entry.delete(0, "end")
            self.search_entry.config(fg=TEXT_PRIMARY)
            self._search_placeholder = False

    def _search_focus_out(self, e=None):
        if not self.search_var.get():
            self.search_entry.insert(0, "Search songs, artists…")
            self.search_entry.config(fg=TEXT_SECONDARY)
            self._search_placeholder = True

    def _on_search_change(self, *args):
        if self._search_placeholder:
            return
        query = self.search_var.get().strip().lower()
        if not query:
            self.filtered_tracks = list(self.all_tracks)
        else:
            self.filtered_tracks = [
                t for t in self.all_tracks
                if query in t["title"].lower() or query in t["artist"].lower()
            ]
        self.current_index = -1
        self._render_track_list()

    # -----------------------------------------------------------------------
    # Theme toggle
    # -----------------------------------------------------------------------
    def _toggle_theme(self):
        self.is_dark = not self.is_dark
        if self.is_dark:
            self.theme_btn.configure(text="☀")
            self._apply_colors(
                bg=BG_DARK, sb=SIDEBAR_BG, card=CARD_BG,
                border=BORDER_CLR, t1=TEXT_PRIMARY, t2=TEXT_SECONDARY,
                active=ACTIVE_BG, hover=HOVER_BG,
            )
        else:
            self.theme_btn.configure(text="🌙")
            self._apply_colors(
                bg=BG_LIGHT, sb=SIDEBAR_LIGHT, card=CARD_LIGHT,
                border=BORDER_LIGHT, t1=TEXT_P_LIGHT, t2=TEXT_S_LIGHT,
                active=ACTIVE_LIGHT, hover=HOVER_LIGHT,
            )

    def _apply_colors(self, bg, sb, card, border, t1, t2, active, hover):
        self.root.configure(bg=bg)
        self.player_panel.configure(bg=bg)
        self.player_inner.configure(bg=bg)
        self.sidebar.configure(bg=sb)
        self.title_label.configure(bg=bg, fg=t1)
        self.artist_label.configure(bg=bg)
        self.album_label.configure(bg=bg, fg=t2)
        self.pos_var.set(self.pos_var.get())
        self.dur_var.set(self.dur_var.get())
        self.play_canvas.configure(bg=bg)
        self._draw_play_button(self.is_playing)
        self.open_btn.configure(bg=ACCENT)
        # Re-render track list
        self._render_track_list()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _add_hover(self, btn: tk.Button, hover_bg: str, normal_bg: str):
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=normal_bg))

    def _on_close(self):
        if self._position_poll_id:
            self.root.after_cancel(self._position_poll_id)
        self.player.close()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    app = MuzeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
