"""
utils.py — Pure-Python utilities for Muze (no third-party packages).

Provides:
  - MCIPlayer      : Windows MCI audio engine via ctypes (winmm.dll)
                     Supports MP3, WAV, WMA, M4A, FLAC (Windows codecs)
  - read_metadata  : Minimal ID3v1 + ID3v2 tag reader (pure Python)
  - scan_directory : Recursively find audio files and read their tags
  - format_duration: Seconds → "M:SS" string
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Windows MCI audio player
# ---------------------------------------------------------------------------
SUPPORTED_EXT = {".mp3", ".wav", ".wma", ".m4a", ".flac", ".aac", ".ogg"}


class MCIPlayer:
    """
    Thin wrapper around Windows MCI (winmm.dll mciSendStringW).

    All MCI commands are sent with millisecond time format.
    Volume range : 0.0 – 1.0  (mapped to MCI 0 – 1000)
    """

    _ALIAS = "muze_track"

    def __init__(self) -> None:
        self._mci = ctypes.windll.winmm.mciSendStringW
        self._buf = ctypes.create_unicode_buffer(512)
        self._open = False
        self._volume: float = 0.8

    # ------------------------------------------------------------------
    # File control
    # ------------------------------------------------------------------
    def open(self, path: str) -> bool:
        if self._open:
            self._cmd(f"close {self._ALIAS}")
            self._open = False
        # Let Windows auto-detect the codec
        safe = str(path).replace('"', '\\"')
        ret = self._cmd(f'open "{safe}" alias {self._ALIAS}')
        if ret == 0:
            self._cmd(f"set {self._ALIAS} time format milliseconds")
            self._apply_volume()
            self._open = True
            return True
        return False

    def close(self) -> None:
        if self._open:
            self._cmd(f"close {self._ALIAS}")
            self._open = False

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def play(self) -> None:
        if self._open:
            self._cmd(f"play {self._ALIAS}")

    def pause(self) -> None:
        if self._open:
            self._cmd(f"pause {self._ALIAS}")

    def resume(self) -> None:
        if self._open:
            self._cmd(f"resume {self._ALIAS}")

    def stop(self) -> None:
        if self._open:
            self._cmd(f"stop {self._ALIAS}")

    def seek(self, ms: int) -> None:
        """Seek to position *ms* (milliseconds) and resume playing."""
        if self._open:
            self._cmd(f"seek {self._ALIAS} to {max(0, int(ms))}")
            self._cmd(f"play {self._ALIAS}")

    # ------------------------------------------------------------------
    # Status queries
    # ------------------------------------------------------------------
    def get_position(self) -> int:
        """Current playback position in milliseconds."""
        return self._query(f"status {self._ALIAS} position")

    def get_length(self) -> int:
        """Total track length in milliseconds."""
        return self._query(f"status {self._ALIAS} length")

    def get_mode(self) -> str:
        """Return MCI mode string: 'playing', 'paused', 'stopped', etc."""
        if not self._open:
            return "closed"
        self._mci(f"status {self._ALIAS} mode", self._buf, 512, 0)
        return self._buf.value.lower()

    # ------------------------------------------------------------------
    # Volume  (0.0 – 1.0)
    # ------------------------------------------------------------------
    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._open:
            v = int(self._volume * 1000)
            self._cmd(f"setaudio {self._ALIAS} volume to {v}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cmd(self, command: str) -> int:
        return self._mci(command, None, 0, 0)

    def _query(self, command: str) -> int:
        ret = self._mci(command, self._buf, 512, 0)
        if ret != 0:
            return 0
        try:
            return int(self._buf.value)
        except ValueError:
            return 0


# ---------------------------------------------------------------------------
# Minimal pure-Python ID3 / metadata reader
# ---------------------------------------------------------------------------

def _decode_text(data: bytes, encoding: int) -> str:
    """Decode ID3 text bytes using the given encoding byte."""
    try:
        if encoding == 0:
            return data.rstrip(b"\x00").decode("latin-1", errors="replace").strip()
        elif encoding == 1:
            # UTF-16 with optional BOM; strip null-pair terminators
            return data.rstrip(b"\x00").decode("utf-16", errors="replace").strip()
        elif encoding == 2:
            return data.rstrip(b"\x00").decode("utf-16-be", errors="replace").strip()
        elif encoding == 3:
            return data.rstrip(b"\x00").decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    return data.rstrip(b"\x00").decode("latin-1", errors="replace").strip()


def _synchsafe_to_int(b: bytes) -> int:
    """Convert 4 synchsafe bytes to a regular integer."""
    n = 0
    for byte in b:
        n = (n << 7) | (byte & 0x7F)
    return n


def _read_id3v1(f) -> dict:
    """Read ID3v1 tag from last 128 bytes."""
    try:
        f.seek(-128, 2)
        tag = f.read(128)
        if tag[:3] != b"TAG":
            return {}
        def dec(b):
            return b.rstrip(b"\x00").decode("latin-1", errors="replace").strip()
        return {
            "title": dec(tag[3:33]),
            "artist": dec(tag[33:63]),
            "album": dec(tag[63:93]),
        }
    except Exception:
        return {}


def _read_id3v2(f) -> dict:
    """
    Read ID3v2.3 / v2.4 tags.
    Extracts: TIT2 (title), TPE1 (artist), TALB (album), APIC (cover art).
    Returns a dict with keys 'title', 'artist', 'album', 'cover' (bytes|None).
    """
    result: dict = {}
    try:
        f.seek(0)
        header = f.read(10)
        if header[:3] != b"ID3":
            return result
        version = header[3]  # major version (3 or 4)
        flags = header[5]
        tag_size = _synchsafe_to_int(header[6:10])
        raw = f.read(tag_size)

        pos = 0
        while pos + 10 <= len(raw):
            fid = raw[pos: pos + 4]
            if fid == b"\x00\x00\x00\x00" or not fid[0:1].isalpha():
                break
            frame_id = fid.decode("latin-1", errors="replace")

            size_bytes = raw[pos + 4: pos + 8]
            if version >= 4:
                frame_size = _synchsafe_to_int(size_bytes)
            else:
                frame_size = struct.unpack(">I", size_bytes)[0]

            pos += 10
            frame_data = raw[pos: pos + frame_size]
            pos += frame_size

            if not frame_data:
                continue

            # --- Text frames ---
            if frame_id in ("TIT2", "TPE1", "TALB"):
                enc = frame_data[0]
                text = _decode_text(frame_data[1:], enc)
                key = {"TIT2": "title", "TPE1": "artist", "TALB": "album"}[frame_id]
                if text:
                    result[key] = text

            # --- Picture frame (APIC) ---
            elif frame_id == "APIC" and "cover" not in result:
                try:
                    enc = frame_data[0]
                    # Find null after MIME type (always Latin-1)
                    null1 = frame_data.index(b"\x00", 1)
                    # pic_type byte after null
                    desc_start = null1 + 2
                    # Find null(s) after description
                    if enc in (1, 2):
                        # UTF-16: two-byte null terminator
                        idx = desc_start
                        while idx + 1 < len(frame_data):
                            if frame_data[idx] == 0 and frame_data[idx + 1] == 0:
                                idx += 2
                                break
                            idx += 2
                        img_start = idx
                    else:
                        null2 = frame_data.index(b"\x00", desc_start)
                        img_start = null2 + 1
                    img_bytes = frame_data[img_start:]
                    if img_bytes:
                        result["cover"] = img_bytes
                except Exception:
                    pass

    except Exception:
        pass
    return result


def read_metadata(path: str) -> dict:
    """
    Read metadata from an audio file.
    Returns a dict with: title, artist, album, cover (bytes|None), path.
    """
    stem = Path(path).stem
    meta: dict = {"title": stem, "artist": "Unknown Artist", "album": "Unknown Album",
                  "cover": None, "path": path}
    try:
        with open(path, "rb") as f:
            v2 = _read_id3v2(f)
            v1 = _read_id3v1(f)
        # Merge: ID3v2 takes priority over v1
        combined = {**v1, **v2}
        if combined.get("title"):
            meta["title"] = combined["title"]
        if combined.get("artist"):
            meta["artist"] = combined["artist"]
        if combined.get("album"):
            meta["album"] = combined["album"]
        if combined.get("cover"):
            meta["cover"] = combined["cover"]
    except Exception:
        pass
    return meta


def scan_directory(directory: str) -> list[dict]:
    """
    Recursively scan *directory* for supported audio files.
    Returns a sorted list of metadata dicts.
    """
    root = Path(directory)
    tracks: list[dict] = []
    for file in root.rglob("*"):
        if file.suffix.lower() in SUPPORTED_EXT:
            tracks.append(read_metadata(str(file)))
    tracks.sort(key=lambda t: (t["artist"].lower(), t["title"].lower()))
    return tracks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_duration(ms: int) -> str:
    """Convert milliseconds to M:SS string."""
    if ms <= 0:
        return "0:00"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"
