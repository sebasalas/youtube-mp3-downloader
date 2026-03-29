# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Direct execution (no build step)
./youtube_mp3_downloader.py

# System-wide install/uninstall (requires sudo)
sudo ./install.sh
sudo ./uninstall.sh

# Run tests
python3 -m pytest tests/ -v
```

**System dependencies:** python3, python-gobject, gtk3, yt-dlp, ffmpeg

## Architecture

GTK 3.0 single-window desktop app that downloads YouTube videos as MP3 using yt-dlp.

**Initialization chain:** `youtube_mp3_downloader.py` → `main.main()` (checks dependencies) → `Application(Gtk.Application)` → `YouTubeMp3Downloader(Gtk.Window)` from `app_window.py`.

### Threading Model

Downloads run in daemon threads (`threading.Thread`). The worker thread spawns yt-dlp via `subprocess.Popen`, parses stdout line-by-line for progress, and marshals all UI updates back to the GTK main loop via `GLib.idle_add()`. Never call GTK methods directly from worker threads.

Cancellation uses `threading.Event` flags (`download_cancel_requested`, `download_stopped`) — the thread checks these via `.is_set()` and calls `process.terminate()` then `process.kill()` after 2s timeout. `cleanup_partial_files()` removes `.part`, `.ytdl`, fragment, and thumbnail artifacts.

`threading.Lock()` protects the `active_download_targets` set and `current_process` to prevent race conditions between the UI thread and download thread.

### Module Responsibilities

- **main.py** — `Application` lifecycle, dependency checking at startup (hard: yt-dlp/ffmpeg; soft: notify-send/xdg-open), app-level actions (preferences, notifications)
- **app_window.py** — Main window UI layout, event handlers, state management, notification sending
- **dialogs.py** — `PreferencesDialog` (auth, browser, notifications settings) and `PlaylistPreviewDialog` (video selection with checkboxes)
- **download.py** — `download_thread()` builds yt-dlp commands, streams output, tracks failures/skips; `cleanup_partial_files()` for stop/error cleanup
- **config.py** — JSON config at `~/.config/youtube-mp3-downloader/config.json` with legacy path migration
- **exceptions.py** — Hierarchy: `YouTubeMp3DownloaderError` → `ConfigurationError`, `DependencyError`, `DownloadError`, `ValidationError`
- **logger.py** — Console (INFO) + rotating file (DEBUG, 5MB×3) at `~/.config/youtube-mp3-downloader/app.log`
- **utils.py** — `classify_youtube_url()` validates and categorizes URLs

### UI Patterns

- Dynamic button states with CSS classes (`suggested-action`, `destructive-action`)
- TextBuffer-based log with auto-scroll
- Progress bar with download speed and ETA parsed from yt-dlp output
- Playlist preview dialog with per-video selection before download
- Preferences dialog accessible from hamburger menu
- Duplicate detection warns before overwriting existing MP3 files
- Notifications via Gio.Notification with `notify-send` fallback
- Browser-selectable cookie authentication (Firefox, Chrome, Brave)

### Testing & CI

- **pytest** tests in `tests/` covering `utils.py` and `config.py` (29 tests)
- **GitHub Actions** CI with flake8 linting, mypy type checking, and pytest
- CI uses system `python3-gi` package (not pip) since PyGObject requires system GTK libraries
- Type hints across all modules using `from __future__ import annotations`

## Language

The codebase uses English for code and documentation. UI strings and install scripts are in Spanish.
