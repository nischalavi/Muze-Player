# Muze - Offline Music Player

A sleek, modern, offline music player built using 100% Python standard library (`tkinter` + `ctypes`). Muze supports native Windows codecs (MP3, WAV, WMA, M4A, FLAC) and features a beautifully designed dark-mode glassmorphic user interface.

## Features
- **Zero Third-Party Dependencies:** Everything is built with standard Python. No `pip` installs required to run the source code on Windows!
- **Modern UI:** Custom-built rounded UI components and beautiful themes using Tkinter Canvas.
- **Full Playback Control:** Play, pause, seek, volume, shuffle, and repeat modes.
- **Fast Search:** Real-time search by track title or artist.
- **Standalone Executable:** Can be packaged into a single `.exe` using PyInstaller.

## Screenshots
*(Add a screenshot of your app here)*

## How to Run from Source
If you want to run the python code directly:
1. Ensure you have Python 3.12+ installed on your Windows machine.
2. Clone this repository.
3. Run `python main.py`

## How to Build the Executable
1. Install PyInstaller: `pip install pyinstaller`
2. Run the build command:
   ```cmd
   pyinstaller --noconsole --onefile --name Muze_Player --icon="assets\default_cover.ico" main.py
   ```
3. The executable will be generated in the `dist/` directory.

## License
MIT License
