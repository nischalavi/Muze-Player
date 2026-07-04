# Implementation Plan - Modern Offline Music Player

A sleek, premium, offline music player desktop application using Python and Flet. Flet builds high-performance, beautiful UI layouts using Flutter, allowing a modern glassmorphic look with responsive controls.

---

## User Review Required

> [!IMPORTANT]
> **Dynamic HTTP Server Port binding**: To play local audio files securely and reliably in the Flet runner, we will run a lightweight, local HTTP server in a daemon thread. This server will bind to a random free port on `localhost` and serve files from the folder currently selected by the user.

---

## Proposed Changes

### Dependencies & Setup

#### [NEW] [requirements.txt](file:///c:/Users/Admin/Documents/Demo1/requirements.txt)
- Add standard requirements:
  - `flet>=0.21.0` (for UI building and audio playback)
  - `tinytag>=1.10.0` (for fast ID3 tag and cover art extraction)

### Core Components

#### [NEW] [utils.py](file:///c:/Users/Admin/Documents/Demo1/utils.py)
- **`ThreadedHTTPServer`**:
  - Starts a lightweight `http.server.SimpleHTTPRequestHandler` in a daemon thread.
  - Automatically binds to an available local port.
  - Serves files from the active scanned folder.
- **`MetadataExtractor`**:
  - Uses `tinytag` to extract Title, Artist, Album, and Duration.
  - Extracts embedded cover art and encodes it as a base64 string for display in the Flet UI.

#### [NEW] [main.py](file:///c:/Users/Admin/Documents/Demo1/main.py)
- **Layout & Design System**:
  - Premium Dark Mode by default with support for toggling.
  - Glassmorphic panels using blurred containers, gradients (deep purple to blue), and rounded borders.
  - Fonts: Inter (or clean system sans-serif).
- **Navigation & Sidebar**:
  - Scanning folder button.
  - Library View (All Songs).
  - Search input box to dynamically filter list by title/artist.
- **Playback Manager**:
  - Built-in `ft.Audio` control integration.
  - Standard control handlers: Play/Pause, Skip Next/Prev, Repeat (None, One, All), Shuffle, Volume.
  - Dynamic Seek slider that synchronizes with playback position.
- **Manual Scan & Folder Selection**:
  - Calls Flet's native `FilePicker` directory selector.
  - Starts the local file server pointing to the selected directory.
  - Recursively scans the directory for `.mp3`, `.wav`, `.m4a`, and `.flac` files, builds the track library, and extracts metadata.

### Asset Assets

#### [NEW] [assets/default_cover.png](file:///c:/Users/Admin/Documents/Demo1/assets/default_cover.png)
- A fallback cover art image for files with no embedded tags or image data.

---

## Verification Plan

### Automated Tests
- Since it is a GUI app, we will verify correctness by running the application.
- Launch the application:
  `venv/Scripts/python.exe main.py`

### Manual Verification
1. **Startup**: Verify the player opens with a welcome screen instructing the user to select a folder.
2. **Directory Selection**: Click the scan button and pick a directory containing `.mp3` files.
3. **Library View**: Confirm songs are parsed and displayed with correct titles, artists, and cover art.
4. **Playback**: Play a song, adjust volume, toggle shuffle/repeat, pause, seek, and transition between tracks.
5. **Search**: Verify searching for a song filters the visible playlist instantly.
6. **Theme Change**: Toggle light/dark modes and verify colors change smoothly.
