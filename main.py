"""
main.py — Modern Offline Music Player
Built with Flet (Flutter-powered Python UI framework).

Features
--------
- Premium glassmorphic dark/light UI with deep purple → blue gradient palette
- Sidebar: folder scan button, search box, track library list
- Now-Playing panel: large cover art, track info, full playback controls
- Playback: Play/Pause, Next, Previous, Seek, Volume, Repeat (Off/One/All), Shuffle
- Local HTTP server (via utils.py) to serve audio files to flet_audio.Audio
- Metadata + embedded cover art via tinytag
"""

import asyncio
import base64
import os
import random
import sys
import threading
from pathlib import Path
from typing import Optional

import flet as ft
import flet_audio as fta

# Ensure the project root is on sys.path so utils.py is importable
sys.path.insert(0, str(Path(__file__).parent))
from utils import ThreadedHTTPServer, format_duration, scan_directory

# ---------------------------------------------------------------------------
# Design Tokens
# ---------------------------------------------------------------------------
DARK_BG = "#0D0D1A"
DARK_SURFACE = "#13132A"
DARK_CARD = "#1A1A35"
DARK_BORDER = "#2A2A55"
DARK_HOVER = "#252550"

LIGHT_BG = "#F0F0F8"
LIGHT_SURFACE = "#FFFFFF"
LIGHT_CARD = "#F5F5FF"
LIGHT_BORDER = "#DDDDF5"
LIGHT_HOVER = "#EAEAF8"

ACCENT_PRIMARY = "#7C3AED"   # Vivid purple
ACCENT_SECONDARY = "#4F46E5"  # Indigo
ACCENT_CYAN = "#06B6D4"
ACCENT_GLOW = "#A78BFA"

TEXT_PRIMARY_DARK = "#F0EEFF"
TEXT_SECONDARY_DARK = "#9B96CC"
TEXT_PRIMARY_LIGHT = "#1A1A3E"
TEXT_SECONDARY_LIGHT = "#5B5B8A"

SIDEBAR_W = 320

# ---------------------------------------------------------------------------
# RepeatMode enum-like constants
# ---------------------------------------------------------------------------
REPEAT_OFF = "off"
REPEAT_ONE = "one"
REPEAT_ALL = "all"


# ---------------------------------------------------------------------------
# Helper: load image bytes → base64 src for ft.Image
# ---------------------------------------------------------------------------
def _b64_src(b64_str: str) -> str:
    return f"data:image/jpeg;base64,{b64_str}"


def _default_cover_src() -> str:
    cover_path = Path(__file__).parent / "assets" / "default_cover.png"
    if cover_path.exists():
        data = cover_path.read_bytes()
        return f"data:image/png;base64,{base64.b64encode(data).decode()}"
    return ""


# ---------------------------------------------------------------------------
# MusicPlayerApp
# ---------------------------------------------------------------------------
class MusicPlayerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.is_dark = True

        # Tracks
        self.all_tracks: list[dict] = []
        self.filtered_tracks: list[dict] = []
        self.current_index: int = -1
        self.shuffle_mode: bool = False
        self.repeat_mode: str = REPEAT_OFF
        self.shuffle_order: list[int] = []

        # Playback state
        self.is_playing: bool = False
        self.duration_ms: float = 0.0
        self.position_ms: float = 0.0
        self.seek_dragging: bool = False
        self.volume: float = 0.8

        # HTTP file server
        self.http_server = ThreadedHTTPServer()

        # Default cover
        self._default_cover = _default_cover_src()

        # Build page
        self._setup_page()
        self._build_audio_control()
        self._build_ui()

    # -----------------------------------------------------------------------
    # Page setup
    # -----------------------------------------------------------------------
    def _setup_page(self):
        p = self.page
        p.title = "Muze — Offline Music Player"
        p.window.width = 1100
        p.window.height = 720
        p.window.min_width = 800
        p.window.min_height = 600
        p.padding = 0
        p.spacing = 0
        p.bgcolor = DARK_BG
        p.fonts = {
            "Inter": "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiA.woff2",
        }
        p.theme = ft.Theme(font_family="Inter")

    # -----------------------------------------------------------------------
    # flet_audio.Audio control — lives in page.overlay
    # -----------------------------------------------------------------------
    def _build_audio_control(self):
        self.audio = fta.Audio(
            src="",
            volume=self.volume,
            on_duration_changed=self._on_duration_changed,
            on_position_changed=self._on_position_changed,
            on_state_changed=self._on_state_changed,
            on_seek_complete=self._on_seek_complete,
        )
        self.page.overlay.append(self.audio)

    # -----------------------------------------------------------------------
    # Build UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        # --- File picker ---
        self.file_picker = ft.FilePicker(on_result=self._on_folder_picked)
        self.page.overlay.append(self.file_picker)

        # --- Sidebar ---
        self.search_field = ft.TextField(
            hint_text="Search songs, artists…",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=12,
            on_change=self._on_search_change,
            text_style=ft.TextStyle(size=13, color=TEXT_PRIMARY_DARK),
            hint_style=ft.TextStyle(size=13, color=TEXT_SECONDARY_DARK),
            border_color=DARK_BORDER,
            focused_border_color=ACCENT_PRIMARY,
            bgcolor=DARK_CARD,
            filled=True,
            height=44,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
        )

        self.scan_btn = ft.ElevatedButton(
            text="Open Folder",
            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
            on_click=self._pick_folder,
            style=ft.ButtonStyle(
                bgcolor={
                    ft.ControlState.DEFAULT: ACCENT_PRIMARY,
                    ft.ControlState.HOVERED: ACCENT_SECONDARY,
                },
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                elevation=0,
            ),
            height=44,
        )

        self.track_count_label = ft.Text(
            "No folder selected",
            size=12,
            color=TEXT_SECONDARY_DARK,
            italic=True,
        )

        self.track_list = ft.ListView(
            spacing=2,
            padding=ft.padding.symmetric(vertical=4),
            expand=True,
        )

        sidebar = ft.Container(
            width=SIDEBAR_W,
            bgcolor=DARK_SURFACE,
            border=ft.Border(right=ft.BorderSide(1, DARK_BORDER)),
            content=ft.Column(
                spacing=0,
                controls=[
                    # Header
                    ft.Container(
                        padding=ft.padding.all(20),
                        content=ft.Column(
                            spacing=12,
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Icon(ft.Icons.MUSIC_NOTE_ROUNDED, color=ACCENT_GLOW, size=28),
                                        ft.Text("muze", size=22, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY_DARK),
                                        ft.Container(expand=True),
                                        ft.IconButton(
                                            icon=ft.Icons.DARK_MODE_ROUNDED,
                                            icon_color=TEXT_SECONDARY_DARK,
                                            icon_size=20,
                                            tooltip="Toggle theme",
                                            on_click=self._toggle_theme,
                                        ),
                                    ]
                                ),
                                self.scan_btn,
                                self.search_field,
                                self.track_count_label,
                            ],
                        ),
                    ),
                    # Divider
                    ft.Divider(height=1, color=DARK_BORDER),
                    # Library list
                    ft.Container(
                        expand=True,
                        content=self.track_list,
                    ),
                ],
            ),
        )

        # --- Now Playing Panel ---
        self.cover_image = ft.Image(
            src=self._default_cover,
            width=220,
            height=220,
            fit=ft.ImageFit.COVER,
            border_radius=16,
        )

        self.track_title = ft.Text(
            "Select a folder to begin",
            size=20,
            weight=ft.FontWeight.BOLD,
            color=TEXT_PRIMARY_DARK,
            text_align=ft.TextAlign.CENTER,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.track_artist = ft.Text(
            "No track playing",
            size=14,
            color=TEXT_SECONDARY_DARK,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.track_album = ft.Text(
            "",
            size=12,
            color=TEXT_SECONDARY_DARK,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            italic=True,
        )

        # Seek slider
        self.position_label = ft.Text("0:00", size=11, color=TEXT_SECONDARY_DARK)
        self.duration_label = ft.Text("0:00", size=11, color=TEXT_SECONDARY_DARK)
        self.seek_slider = ft.Slider(
            min=0,
            max=1,
            value=0,
            active_color=ACCENT_PRIMARY,
            inactive_color=DARK_BORDER,
            thumb_color=ACCENT_GLOW,
            on_change=self._on_seek_drag,
            on_change_end=self._on_seek_end,
            expand=True,
            height=20,
        )

        # Playback buttons
        self.shuffle_btn = ft.IconButton(
            icon=ft.Icons.SHUFFLE_ROUNDED,
            icon_color=TEXT_SECONDARY_DARK,
            icon_size=22,
            tooltip="Shuffle",
            on_click=self._toggle_shuffle,
        )
        self.prev_btn = ft.IconButton(
            icon=ft.Icons.SKIP_PREVIOUS_ROUNDED,
            icon_color=TEXT_PRIMARY_DARK,
            icon_size=32,
            tooltip="Previous",
            on_click=self._prev_track,
        )
        self.play_pause_btn = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_ROUNDED,
            icon_color=ACCENT_GLOW,
            icon_size=64,
            tooltip="Play / Pause",
            on_click=self._toggle_play_pause,
        )
        self.next_btn = ft.IconButton(
            icon=ft.Icons.SKIP_NEXT_ROUNDED,
            icon_color=TEXT_PRIMARY_DARK,
            icon_size=32,
            tooltip="Next",
            on_click=self._next_track,
        )
        self.repeat_btn = ft.IconButton(
            icon=ft.Icons.REPEAT_ROUNDED,
            icon_color=TEXT_SECONDARY_DARK,
            icon_size=22,
            tooltip="Repeat: Off",
            on_click=self._cycle_repeat,
        )

        # Volume
        self.volume_icon = ft.Icon(ft.Icons.VOLUME_UP_ROUNDED, color=TEXT_SECONDARY_DARK, size=20)
        self.volume_slider = ft.Slider(
            min=0,
            max=1,
            value=self.volume,
            active_color=ACCENT_PRIMARY,
            inactive_color=DARK_BORDER,
            thumb_color=ACCENT_GLOW,
            width=120,
            height=20,
            on_change=self._on_volume_change,
        )

        # Assemble now-playing panel
        now_playing = ft.Container(
            expand=True,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[DARK_BG, "#0F0A2A", "#0A0A20"],
            ),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                controls=[
                    # Cover art with glow
                    ft.Container(
                        margin=ft.margin.only(bottom=24, top=20),
                        content=ft.Stack(
                            controls=[
                                # Glow shadow behind the image
                                ft.Container(
                                    width=220,
                                    height=220,
                                    border_radius=20,
                                    bgcolor=ACCENT_PRIMARY,
                                    opacity=0.15,
                                    margin=ft.margin.all(4),
                                    shadow=ft.BoxShadow(
                                        blur_radius=40,
                                        color=ACCENT_PRIMARY,
                                        offset=ft.Offset(0, 0),
                                        spread_radius=10,
                                    ),
                                ),
                                ft.Container(
                                    content=self.cover_image,
                                    shadow=ft.BoxShadow(
                                        blur_radius=30,
                                        color="#44000000",
                                        offset=ft.Offset(0, 10),
                                    ),
                                ),
                            ]
                        ),
                    ),
                    # Track info
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=40),
                        width=600,
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            controls=[
                                self.track_title,
                                self.track_artist,
                                self.track_album,
                            ],
                        ),
                    ),
                    ft.Container(height=20),
                    # Seek bar
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=40),
                        width=560,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=8,
                            controls=[
                                self.position_label,
                                self.seek_slider,
                                self.duration_label,
                            ],
                        ),
                    ),
                    ft.Container(height=8),
                    # Main controls
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=4,
                        controls=[
                            self.shuffle_btn,
                            self.prev_btn,
                            self.play_pause_btn,
                            self.next_btn,
                            self.repeat_btn,
                        ],
                    ),
                    ft.Container(height=8),
                    # Volume
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                        controls=[
                            self.volume_icon,
                            self.volume_slider,
                        ],
                    ),
                    ft.Container(height=20),
                ],
            ),
        )

        # Store refs for theme updates
        self.sidebar_container = sidebar
        self.now_playing_container = now_playing

        root = ft.Row(
            spacing=0,
            expand=True,
            controls=[sidebar, now_playing],
        )
        self.page.add(root)
        self.page.update()

    # -----------------------------------------------------------------------
    # Folder picker
    # -----------------------------------------------------------------------
    def _pick_folder(self, e):
        self.file_picker.get_directory_path(dialog_title="Select Music Folder")

    def _on_folder_picked(self, e):
        if not e.path:
            return
        folder = e.path
        self.http_server.serve_directory(folder)
        self._scan_and_load(folder)

    def _scan_and_load(self, folder: str):
        """Run scanning in a thread to keep the UI responsive."""
        self.track_count_label.value = "Scanning…"
        self.track_count_label.update()

        def _do_scan():
            tracks = scan_directory(folder)
            self.all_tracks = tracks
            self.filtered_tracks = list(tracks)
            self._refresh_track_list()
            count = len(tracks)
            label = f"{count} track{'s' if count != 1 else ''} found"
            self.track_count_label.value = label
            self.track_count_label.update()

        threading.Thread(target=_do_scan, daemon=True).start()

    # -----------------------------------------------------------------------
    # Track list rendering
    # -----------------------------------------------------------------------
    def _refresh_track_list(self):
        self.track_list.controls.clear()
        for idx, track in enumerate(self.filtered_tracks):
            is_active = (
                self.current_index >= 0
                and self.filtered_tracks[self.current_index]["path"] == track["path"]
                if self.current_index < len(self.filtered_tracks)
                else False
            )
            self.track_list.controls.append(self._build_track_tile(idx, track, is_active))
        self.track_list.update()

    def _build_track_tile(self, idx: int, track: dict, is_active: bool = False) -> ft.Control:
        title = track["title"]
        artist = track["artist"]
        dur = format_duration(track["duration"])

        # Small cover thumbnail
        if track.get("cover_b64"):
            thumb = ft.Image(
                src=_b64_src(track["cover_b64"]),
                width=44,
                height=44,
                fit=ft.ImageFit.COVER,
                border_radius=8,
            )
        else:
            thumb = ft.Container(
                width=44,
                height=44,
                border_radius=8,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_left,
                    end=ft.alignment.bottom_right,
                    colors=[ACCENT_PRIMARY, ACCENT_SECONDARY],
                ),
                content=ft.Icon(ft.Icons.MUSIC_NOTE, color=ft.Colors.WHITE, size=20),
            )

        bg_color = ACCENT_PRIMARY + "33" if is_active else "transparent"
        border = ft.Border(left=ft.BorderSide(3, ACCENT_GLOW)) if is_active else None

        tile = ft.Container(
            key=str(idx),
            bgcolor=bg_color,
            border=border,
            border_radius=ft.BorderRadius(0, 8, 8, 0),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            ink=True,
            on_click=lambda e, i=idx: self._play_track(i),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    thumb,
                    ft.Column(
                        spacing=2,
                        expand=True,
                        controls=[
                            ft.Text(
                                title,
                                size=13,
                                weight=ft.FontWeight.W_500 if is_active else ft.FontWeight.NORMAL,
                                color=ACCENT_GLOW if is_active else TEXT_PRIMARY_DARK,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                artist,
                                size=11,
                                color=TEXT_SECONDARY_DARK,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                    ),
                    ft.Text(dur, size=11, color=TEXT_SECONDARY_DARK),
                ],
            ),
        )
        return tile

    # -----------------------------------------------------------------------
    # Playback control
    # -----------------------------------------------------------------------
    def _play_track(self, idx: int):
        if not self.filtered_tracks or idx < 0 or idx >= len(self.filtered_tracks):
            return
        self.current_index = idx
        track = self.filtered_tracks[idx]

        url = self.http_server.url_for(track["path"])
        self.audio.src = url
        self.audio.update()
        self.audio.play()
        self.is_playing = True
        self._update_now_playing(track)
        self._update_play_button()
        self._refresh_track_list()

    def _toggle_play_pause(self, e):
        if self.current_index < 0 and self.filtered_tracks:
            self._play_track(0)
            return
        if self.is_playing:
            self.audio.pause()
            self.is_playing = False
        else:
            self.audio.resume()
            self.is_playing = True
        self._update_play_button()

    def _prev_track(self, e):
        if not self.filtered_tracks:
            return
        if self.position_ms > 3000:
            # If more than 3 s in, restart current
            self.audio.seek(ft.Duration(milliseconds=0))
            return
        target = self._get_prev_idx()
        self._play_track(target)

    def _next_track(self, e):
        if not self.filtered_tracks:
            return
        target = self._get_next_idx()
        if target == -1:
            # End of playlist, stop
            self.audio.pause()
            self.is_playing = False
            self._update_play_button()
            return
        self._play_track(target)

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
                if self.repeat_mode == REPEAT_ALL:
                    self._build_shuffle_order()
                    return self.shuffle_order[0]
                return -1
            except ValueError:
                return self.shuffle_order[0] if self.shuffle_order else -1
        else:
            if self.current_index + 1 < n:
                return self.current_index + 1
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
                return self.current_index
        else:
            return max(0, self.current_index - 1)

    def _build_shuffle_order(self):
        n = len(self.filtered_tracks)
        order = list(range(n))
        random.shuffle(order)
        self.shuffle_order = order

    def _toggle_shuffle(self, e):
        self.shuffle_mode = not self.shuffle_mode
        if self.shuffle_mode:
            self._build_shuffle_order()
            self.shuffle_btn.icon_color = ACCENT_GLOW
        else:
            self.shuffle_btn.icon_color = TEXT_SECONDARY_DARK
        self.shuffle_btn.update()

    def _cycle_repeat(self, e):
        if self.repeat_mode == REPEAT_OFF:
            self.repeat_mode = REPEAT_ALL
            self.repeat_btn.icon = ft.Icons.REPEAT_ROUNDED
            self.repeat_btn.icon_color = ACCENT_GLOW
            self.repeat_btn.tooltip = "Repeat: All"
        elif self.repeat_mode == REPEAT_ALL:
            self.repeat_mode = REPEAT_ONE
            self.repeat_btn.icon = ft.Icons.REPEAT_ONE_ROUNDED
            self.repeat_btn.icon_color = ACCENT_PRIMARY
            self.repeat_btn.tooltip = "Repeat: One"
        else:
            self.repeat_mode = REPEAT_OFF
            self.repeat_btn.icon = ft.Icons.REPEAT_ROUNDED
            self.repeat_btn.icon_color = TEXT_SECONDARY_DARK
            self.repeat_btn.tooltip = "Repeat: Off"
        self.repeat_btn.update()

    # -----------------------------------------------------------------------
    # Audio events
    # -----------------------------------------------------------------------
    def _on_duration_changed(self, e):
        try:
            self.duration_ms = float(e.data)
        except (ValueError, TypeError):
            self.duration_ms = 0.0
        dur_s = self.duration_ms / 1000
        self.duration_label.value = format_duration(dur_s)
        self.duration_label.update()

    def _on_position_changed(self, e):
        try:
            self.position_ms = float(e.data)
        except (ValueError, TypeError):
            self.position_ms = 0.0

        if not self.seek_dragging and self.duration_ms > 0:
            self.seek_slider.value = self.position_ms / self.duration_ms
            pos_s = self.position_ms / 1000
            self.position_label.value = format_duration(pos_s)
            try:
                self.seek_slider.update()
                self.position_label.update()
            except Exception:
                pass

    def _on_state_changed(self, e):
        state = e.data if e.data else ""
        if state == "playing":
            self.is_playing = True
        elif state in ("paused", "stopped"):
            self.is_playing = False
        elif state == "completed":
            self.is_playing = False
            self._handle_track_complete()
        self._update_play_button()

    def _on_seek_complete(self, e):
        self.seek_dragging = False

    def _handle_track_complete(self):
        if self.repeat_mode == REPEAT_ONE:
            self._play_track(self.current_index)
        else:
            self._next_track(None)

    # -----------------------------------------------------------------------
    # Seek slider interactions
    # -----------------------------------------------------------------------
    def _on_seek_drag(self, e):
        self.seek_dragging = True
        if self.duration_ms > 0:
            pos_s = float(e.control.value) * self.duration_ms / 1000
            self.position_label.value = format_duration(pos_s)
            self.position_label.update()

    def _on_seek_end(self, e):
        if self.duration_ms > 0:
            target_ms = int(float(e.control.value) * self.duration_ms)
            self.audio.seek(ft.Duration(milliseconds=target_ms))
        self.seek_dragging = False

    # -----------------------------------------------------------------------
    # Volume
    # -----------------------------------------------------------------------
    def _on_volume_change(self, e):
        self.volume = float(e.control.value)
        self.audio.volume = self.volume
        self.audio.update()
        if self.volume == 0:
            self.volume_icon.name = ft.Icons.VOLUME_OFF_ROUNDED
        elif self.volume < 0.5:
            self.volume_icon.name = ft.Icons.VOLUME_DOWN_ROUNDED
        else:
            self.volume_icon.name = ft.Icons.VOLUME_UP_ROUNDED
        self.volume_icon.update()

    # -----------------------------------------------------------------------
    # Update now-playing display
    # -----------------------------------------------------------------------
    def _update_now_playing(self, track: dict):
        self.track_title.value = track["title"]
        self.track_artist.value = track["artist"]
        self.track_album.value = track["album"] if track["album"] != "Unknown Album" else ""

        if track.get("cover_b64"):
            self.cover_image.src = _b64_src(track["cover_b64"])
        else:
            self.cover_image.src = self._default_cover

        self.seek_slider.value = 0
        self.position_label.value = "0:00"
        self.duration_label.value = format_duration(track["duration"])

        try:
            self.track_title.update()
            self.track_artist.update()
            self.track_album.update()
            self.cover_image.update()
            self.seek_slider.update()
            self.position_label.update()
            self.duration_label.update()
        except Exception:
            pass

    def _update_play_button(self):
        if self.is_playing:
            self.play_pause_btn.icon = ft.Icons.PAUSE_CIRCLE_ROUNDED
        else:
            self.play_pause_btn.icon = ft.Icons.PLAY_CIRCLE_ROUNDED
        try:
            self.play_pause_btn.update()
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------
    def _on_search_change(self, e):
        query = e.control.value.strip().lower()
        if not query:
            self.filtered_tracks = list(self.all_tracks)
        else:
            self.filtered_tracks = [
                t for t in self.all_tracks
                if query in t["title"].lower() or query in t["artist"].lower()
            ]
        self.current_index = -1
        self._refresh_track_list()

    # -----------------------------------------------------------------------
    # Theme toggle
    # -----------------------------------------------------------------------
    def _toggle_theme(self, e):
        self.is_dark = not self.is_dark
        self._apply_theme()

    def _apply_theme(self):
        if self.is_dark:
            bg = DARK_BG
            surface = DARK_SURFACE
            border_clr = DARK_BORDER
            text1 = TEXT_PRIMARY_DARK
            text2 = TEXT_SECONDARY_DARK
            card = DARK_CARD
        else:
            bg = LIGHT_BG
            surface = LIGHT_SURFACE
            border_clr = LIGHT_BORDER
            text1 = TEXT_PRIMARY_LIGHT
            text2 = TEXT_SECONDARY_LIGHT
            card = LIGHT_CARD

        self.page.bgcolor = bg

        # Sidebar
        self.sidebar_container.bgcolor = surface
        self.sidebar_container.border = ft.Border(right=ft.BorderSide(1, border_clr))

        # Search field
        self.search_field.bgcolor = card
        self.search_field.border_color = border_clr
        self.search_field.text_style = ft.TextStyle(size=13, color=text1)
        self.search_field.hint_style = ft.TextStyle(size=13, color=text2)

        # Labels
        self.track_count_label.color = text2
        self.track_title.color = text1
        self.track_artist.color = text2
        self.track_album.color = text2
        self.position_label.color = text2
        self.duration_label.color = text2

        # Volume
        self.volume_icon.color = text2

        # Track list tiles  — rebuild with new colours
        self._refresh_track_list()

        self.page.update()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(page: ft.Page):
    MusicPlayerApp(page)


if __name__ == "__main__":
    ft.run(
        target=main,
        assets_dir="assets",
    )
