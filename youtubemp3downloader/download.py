
import subprocess
import re
import os
import glob
from pathlib import Path
from gi.repository import GLib

def download_thread(window, url, url_type, download_path, use_auth):
    """Run yt-dlp in a separate thread"""
    try:
        playlist_info = {}
        should_fetch_playlist_info = (url_type == "Playlist") or use_auth
        if should_fetch_playlist_info:
            try:
                GLib.idle_add(window.log_message, "Getting playlist information...")
                info_cmd = [
                    "yt-dlp",
                    "--flat-playlist",
                    "--print",
                    "%(id)s:::%(playlist_index|)s%(playlist_index& - |)s%(title)s",
                ]
                if use_auth:
                    info_cmd.extend(["--cookies-from-browser", "firefox"])
                info_cmd.append(url)

                info_process = subprocess.run(info_cmd, capture_output=True, text=True, timeout=60)
                if info_process.returncode == 0:
                    for line in info_process.stdout.strip().split('\n'):
                        if ':::' in line:
                            parts = line.split(':::', 1)
                            if len(parts) == 2:
                                video_id = parts[0].strip()
                                title = parts[1].strip()
                                playlist_info[video_id] = title
                    GLib.idle_add(window.log_message, "✓ Playlist information obtained: {} videos".format(len(playlist_info)))
                    GLib.idle_add(window.log_message, "")
            except Exception as e:
                GLib.idle_add(window.log_message, "⚠ Could not get playlist info: {}".format(str(e)))
                GLib.idle_add(window.log_message, "")

        if window.download_cancel_requested:
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "✓ Download cancelled before starting")
            return

        output_template = str(Path(download_path) / "%(playlist_index|)s%(playlist_index& - |)s%(title)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "320k",
            "--postprocessor-args", "ffmpeg:-b:a 320k",
            "--embed-thumbnail",
            "--add-metadata",
            "--yes-playlist",
            "--ignore-errors",
            "-o", output_template,
        ]

        if use_auth:
            cmd.extend(["--cookies-from-browser", "firefox"])
            GLib.idle_add(window.log_message, "🔐 Authentication enabled: using Firefox cookies")
            GLib.idle_add(window.log_message, "   (Make sure you are logged into YouTube in Firefox)")
            GLib.idle_add(window.log_message, "")

        cmd.append(url)

        GLib.idle_add(window.log_message, "Running: {}".format(' '.join(cmd)))
        GLib.idle_add(window.log_message, "")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        window.current_process = process

        current_video_title = ""
        successful_downloads = 0
        failed_downloads = 0
        failed_videos = []
        current_video_index = 0
        total_videos = 0

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            if line.startswith("[TITLE]"):
                current_video_title = line.replace("[TITLE]", "", 1)
                continue

            if "[download] Downloading item" in line or "[download] Downloading video" in line:
                try:
                    import_match = re.search(r'Downloading (?:item|video) (\d+) of (\d+)', line)
                    if import_match:
                        current_video_index = int(import_match.group(1))
                        total_videos = int(import_match.group(2))
                        if not current_video_title:
                            current_video_title = "Video #{}".format(current_video_index)
                except Exception:
                    pass

            GLib.idle_add(window.log_message, line)

            if "[download] Destination:" in line:
                try:
                    window.current_downloading_file = line.split("[download] Destination:")[1].strip()
                    window.current_download_original = window.current_downloading_file
                    with window.download_lock:
                        window.active_download_targets.add(window.current_download_original)

                    filename = os.path.basename(window.current_downloading_file)
                    current_video_title = os.path.splitext(filename)[0]
                except Exception:
                    pass

            if "Deleting original file" in line:
                successful_downloads += 1
                if window.current_download_original:
                    with window.download_lock:
                        window.active_download_targets.discard(window.current_download_original)
                window.current_downloading_file = None
                window.current_download_original = None
                current_video_title = ""

            if "ERROR:" in line:
                video_identifier = current_video_title

                if not video_identifier:
                    try:
                        match = re.search(r'\[youtube\]\s+([A-Za-z0-9_-]+):', line)
                        if match:
                            video_id = match.group(1)
                            video_identifier = playlist_info.get(video_id, "ID: {}".format(video_id))
                        else:
                            video_identifier = "Unknown"
                    except Exception:
                        video_identifier = "Unknown"

                error_info = {
                    "line": line,
                    "video_context": video_identifier
                }

                if any(keyword in line for keyword in [
                    "Video unavailable",
                    "This video has been",
                    "Private video",
                    "This video is no longer available",
                    "removed by the uploader",
                    "account associated with this video has been terminated",
                    "Video is not available",
                    "Members-only",
                    "Join this channel to get access",
                    "This live stream recording is not available"
                ]):
                    failed_downloads += 1
                    failed_videos.append(error_info)
                    if window.current_download_original:
                        with window.download_lock:
                            window.active_download_targets.discard(window.current_download_original)
                    window.current_downloading_file = None
                    window.current_download_original = None
                    current_video_title = ""

            if "[download] Downloading item" in line or "[download] Downloading video" in line:
                if total_videos > 0:
                    playlist_status = "Video {}/{}".format(current_video_index, total_videos)
                    GLib.idle_add(window.progress_bar.set_text, playlist_status)
                else:
                    GLib.idle_add(window.progress_bar.set_text, "Downloading playlist...")

            if "%" in line and "ETA" in line:
                try:
                    parts = line.split()
                    for part in parts:
                        if "%" in part:
                            percent = float(part.replace("%", ""))
                            GLib.idle_add(window.progress_bar.set_fraction, percent / 100)
                            if total_videos > 0:
                                progress_text = "Video {}/{} - {:.1f}%".format(current_video_index, total_videos, percent)
                            else:
                                progress_text = "{:.1f}%".format(percent)
                            GLib.idle_add(window.progress_bar.set_text, progress_text)
                            break
                except Exception:
                    pass

        process.wait()

        if window.download_stopped:
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)
            if successful_downloads > 0:
                GLib.idle_add(window.log_message, "ℹ Download stopped. Files completed before stopping: {}".format(successful_downloads))
            else:
                GLib.idle_add(window.log_message, "ℹ Download stopped. No files were completed.")
            return

        if successful_downloads > 0:
            GLib.idle_add(window.progress_bar.set_fraction, 1.0)
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)

            if failed_downloads > 0:
                GLib.idle_add(window.progress_bar.set_text, "Completed with warnings")
                GLib.idle_add(window.log_message, "✓ Download completed: {} file(s) downloaded".format(successful_downloads))
                GLib.idle_add(window.log_message, "⚠ Warning: {} video(s) unavailable or failed".format(failed_downloads))

                if failed_videos:
                    GLib.idle_add(window.log_message, "")
                    GLib.idle_add(window.log_message, "Failed videos:")
                    GLib.idle_add(window.log_message, "-" * 60)
                    for i, failed in enumerate(failed_videos, 1):
                        GLib.idle_add(window.log_message, "{}. {}".format(i, failed['video_context']))
                        GLib.idle_add(window.log_message, "   Error: {}".format(failed['line']))
                    GLib.idle_add(window.log_message, "-" * 60)

                GLib.idle_add(window.show_success_dialog,
                                "Download completed!\n\n✓ {} file(s) downloaded\n⚠ {} video(s) unavailable".format(successful_downloads, failed_downloads))
                GLib.idle_add(window.send_notification,
                                "Download completed with warnings",
                                "{} file(s) downloaded, {} unavailable".format(successful_downloads, failed_downloads),
                                "dialog-warning")
            else:
                GLib.idle_add(window.progress_bar.set_text, "Completed!")
                GLib.idle_add(window.log_message, "✓ Download completed successfully: {} file(s)".format(successful_downloads))
                GLib.idle_add(window.show_success_dialog, "Download completed successfully!\n\n{} file(s) downloaded".format(successful_downloads))
                GLib.idle_add(window.send_notification,
                                "Download completed!",
                                "{} file(s) downloaded successfully".format(successful_downloads),
                                "emblem-default")
        elif process.returncode == 0:
            GLib.idle_add(window.progress_bar.set_fraction, 1.0)
            GLib.idle_add(window.progress_bar.set_text, "Completed!")
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)
            GLib.idle_add(window.log_message, "✓ Process completed")
            GLib.idle_add(window.show_success_dialog, "Process completed!")
            GLib.idle_add(window.send_notification,
                            "Process completed",
                            "The download process has finished",
                            "dialog-information")
        else:
            GLib.idle_add(window.progress_bar.set_text, "Error")
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "✗ Error: Could not download any files (code {})".format(process.returncode))
            GLib.idle_add(window.show_error_dialog, "Error: Could not download any files.\nCheck the log for more details.")

    except Exception as e:
        GLib.idle_add(window.log_message, "✗ Error: {}".format(str(e)))
        GLib.idle_add(window.show_error_dialog, "Error: {}".format(str(e)))
        GLib.idle_add(window.progress_bar.set_text, "Error")
    finally:
        window.current_process = None
        window.current_downloading_file = None
        window.current_download_original = None

        def restore_download_button():
            window.download_button.set_sensitive(True)
            window.download_button.get_style_context().add_class("suggested-action")

        def restore_stop_button():
            window.stop_button.set_sensitive(False)
            window.stop_button.get_style_context().remove_class("destructive-action")

        GLib.idle_add(restore_download_button)
        GLib.idle_add(restore_stop_button)
        GLib.idle_add(window.copy_log_button.show)
        GLib.idle_add(window._set_ui_sensitive, True)


def cleanup_partial_files(window):
    """Delete partial files left by yt-dlp when the download is stopped"""
    try:
        files_deleted = 0
        with window.download_lock:
            targets = list(window.active_download_targets)

        for target in targets:
            try:
                base, original_ext = os.path.splitext(target)
                candidates = [
                    target,
                    f"{target}.part",
                    f"{target}.ytdl",
                    f"{target}.temp",
                ]

                for candidate in candidates:
                    if os.path.isfile(candidate):
                        os.remove(candidate)
                        filename = os.path.basename(candidate)
                        window.log_message("🗑 Deleted partial file: {}".format(filename))
                        files_deleted += 1

                for wildcard in [f"{base}.f*", f"{base}.fragment*", f"{base}.frag*"]:
                    for candidate in glob.glob(wildcard):
                        if os.path.isfile(candidate):
                            os.remove(candidate)
                            filename = os.path.basename(candidate)
                            window.log_message("🗑 Deleted residual chunk: {}".format(filename))
                            files_deleted += 1

                for thumbnail in [f"{base}.jpg", f"{base}.jpeg", f"{base}.png", f"{base}.webp"]:
                    if os.path.isfile(thumbnail):
                        os.remove(thumbnail)
                        filename = os.path.basename(thumbnail)
                        window.log_message("🗑 Deleted residual thumbnail: {}".format(filename))
                        files_deleted += 1

                mp3_candidate = f"{base}.mp3"
                if os.path.isfile(mp3_candidate):
                    if os.path.getsize(mp3_candidate) < 1024:
                        os.remove(mp3_candidate)
                        filename = os.path.basename(mp3_candidate)
                        window.log_message("🗑 Deleted incomplete MP3: {}".format(filename))
                        files_deleted += 1
            except Exception as file_error:
                window.log_message("⚠ Could not clean {}: {}".format(os.path.basename(target), str(file_error)))

        with window.download_lock:
            for target in targets:
                window.active_download_targets.discard(target)

        if files_deleted > 0:
            window.log_message("✓ {} partial file(s) deleted".format(files_deleted))
        else:
            window.log_message("ℹ No partial files found to delete")

    except Exception as e:
        window.log_message("⚠ Error cleaning partial files: {}".format(str(e)))
