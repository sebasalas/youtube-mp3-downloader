
from __future__ import annotations

import subprocess
import re
import os
import glob
from typing import TYPE_CHECKING, Optional
from pathlib import Path
from gi.repository import GLib

from .exceptions import DownloadError, ValidationError
from .logger import get_logger

if TYPE_CHECKING:
    from .app_window import YouTubeMp3Downloader

logger = get_logger(__name__)


def download_thread(
    window: YouTubeMp3Downloader,
    url: str,
    url_type: str,
    download_path: str,
    use_auth: bool,
    auth_browser: str = "firefox",
    playlist_items: Optional[str] = None,
) -> None:
    """Run yt-dlp in a separate thread"""
    logger.info(f"Download thread started for {url_type}: {url}")

    try:
        # Validate download path
        if not download_path or not os.path.isdir(download_path):
            logger.error(f"Invalid download path: {download_path}")
            raise ValidationError(f"Download path is not a valid directory: {download_path}")

        if not os.access(download_path, os.W_OK):
            logger.error(f"Download path not writable: {download_path}")
            raise ValidationError(f"Download path is not writable: {download_path}")

        playlist_info = {}
        should_fetch_playlist_info = ((url_type == "Playlist") or use_auth) and not playlist_items
        if should_fetch_playlist_info:
            try:
                GLib.idle_add(window.log_message, "Getting playlist information...")
                logger.debug("Fetching playlist information...")
                info_cmd = [
                    "yt-dlp",
                    "--flat-playlist",
                    "--print",
                    "%(id)s:::%(playlist_index|)s%(playlist_index& - |)s%(title)s",
                ]
                if use_auth:
                    info_cmd.extend(["--cookies-from-browser", auth_browser])
                info_cmd.append(url)

                info_process = subprocess.run(
                    info_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if info_process.returncode == 0:
                    for line in info_process.stdout.strip().split('\n'):
                        if ':::' in line:
                            parts = line.split(':::', 1)
                            if len(parts) == 2:
                                video_id = parts[0].strip()
                                title = parts[1].strip()
                                playlist_info[video_id] = title
                    GLib.idle_add(
                        window.log_message,
                        "✓ Playlist information obtained: {} videos".format(len(playlist_info))
                    )
                    GLib.idle_add(window.log_message, "")
                    logger.info(f"Playlist info retrieved: {len(playlist_info)} videos")
                else:
                    logger.warning(f"Failed to get playlist info, return code: {info_process.returncode}")
            except subprocess.TimeoutExpired:
                logger.warning("Playlist info fetch timed out after 60 seconds")
                GLib.idle_add(window.log_message, "⚠ Playlist info fetch timed out, continuing anyway")
                GLib.idle_add(window.log_message, "")
            except subprocess.SubprocessError as e:
                logger.warning(f"Subprocess error getting playlist info: {e}")
                GLib.idle_add(window.log_message, "⚠ Could not get playlist info: {}".format(str(e)))
                GLib.idle_add(window.log_message, "")
            except Exception as e:
                logger.warning(f"Unexpected error getting playlist info: {e}")
                GLib.idle_add(window.log_message, "⚠ Could not get playlist info: {}".format(str(e)))
                GLib.idle_add(window.log_message, "")

        if window.download_cancel_requested.is_set():
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "✓ Download cancelled before starting")
            logger.info("Download cancelled by user before starting")
            return

        output_template = str(Path(download_path) / "%(playlist_index|)s%(playlist_index& - |)s%(title)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--postprocessor-args", "ffmpeg:-b:a 320k",
            "--embed-thumbnail",
            "--add-metadata",
            "--yes-playlist",
            "--ignore-errors",
            "--retries", "3",
            "--fragment-retries", "3",
            "--socket-timeout", "30",
            "-o", output_template,
        ]

        if playlist_items:
            cmd.extend(["--playlist-items", playlist_items])
            logger.info(f"Downloading selected playlist items: {playlist_items}")

        if use_auth:
            cmd.extend(["--cookies-from-browser", auth_browser])
            browser_name = auth_browser.capitalize()
            GLib.idle_add(window.log_message, "🔐 Authentication enabled: using {} cookies".format(browser_name))
            GLib.idle_add(window.log_message, "   (Make sure you are logged into YouTube in {})".format(browser_name))
            GLib.idle_add(window.log_message, "")
            logger.info("Using %s cookies for authentication", browser_name)

        cmd.append(url)

        GLib.idle_add(window.log_message, "Running: {}".format(' '.join(cmd)))
        GLib.idle_add(window.log_message, "")
        logger.debug(f"Executing command: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"Failed to start yt-dlp process: {e}")
            raise DownloadError(f"Could not start download process: {e}") from e

        with window.download_lock:
            window.current_process = process
        logger.debug(f"Download process started with PID: {process.pid}")

        current_video_title = ""
        successful_downloads = 0
        failed_downloads = 0
        skipped_downloads = 0
        skipped_videos = []
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
                except (ValueError, AttributeError) as e:
                    logger.debug(f"Could not parse video index from line: {e}")

            GLib.idle_add(window.log_message, line)

            if "[download] Destination:" in line:
                try:
                    window.current_downloading_file = line.split("[download] Destination:")[1].strip()
                    window.current_download_original = window.current_downloading_file
                    with window.download_lock:
                        window.active_download_targets.add(window.current_download_original)

                    filename = os.path.basename(window.current_downloading_file)
                    current_video_title = os.path.splitext(filename)[0]

                    # Duplicate detection: check if MP3 already exists
                    base, _ = os.path.splitext(window.current_downloading_file)
                    existing_mp3 = base + ".mp3"
                    if os.path.isfile(existing_mp3) and os.path.getsize(existing_mp3) > 1024:
                        mp3_name = os.path.basename(existing_mp3)
                        GLib.idle_add(window.log_message, "⚠ Already exists, will be overwritten: {}".format(mp3_name))
                        logger.info(f"Duplicate detected: {mp3_name}")
                except (IndexError, AttributeError) as e:
                    logger.debug(f"Could not parse destination from line: {e}")

            if "has already been downloaded" in line:
                skipped_downloads += 1
                video_name = current_video_title or "Unknown"
                skipped_videos.append(video_name)
                GLib.idle_add(window.log_message, "⏭ Skipped (already exists): {}".format(video_name))
                logger.info(f"Skipped duplicate: {video_name}")
                if window.current_download_original:
                    with window.download_lock:
                        window.active_download_targets.discard(window.current_download_original)
                window.current_downloading_file = None
                window.current_download_original = None
                current_video_title = ""

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
                    except (AttributeError, IndexError) as e:
                        logger.debug(f"Could not extract video ID from error line: {e}")
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

            if "%" in line and "[download]" in line:
                try:
                    parts = line.split()
                    percent = None
                    speed = None
                    eta = None
                    for i, part in enumerate(parts):
                        if "%" in part:
                            try:
                                percent = float(part.replace("%", ""))
                            except ValueError:
                                pass
                        if part == "at" and i + 1 < len(parts):
                            speed = parts[i + 1]
                        if part == "ETA" and i + 1 < len(parts):
                            eta = parts[i + 1]

                    if percent is not None:
                        GLib.idle_add(window.progress_bar.set_fraction, percent / 100)
                        if total_videos > 0:
                            progress_text = "Video {}/{} - {:.1f}%".format(current_video_index, total_videos, percent)
                        else:
                            progress_text = "{:.1f}%".format(percent)
                        if speed:
                            progress_text += " | {}".format(speed)
                        if eta:
                            progress_text += " | ETA {}".format(eta)
                        GLib.idle_add(window.progress_bar.set_text, progress_text)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse progress: {e}")

        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not exit after stdout closed, killing")
            process.kill()
            process.wait(timeout=10)
        logger.info(f"Download process completed with return code: {process.returncode}")

        if window.download_stopped.is_set():
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)
            if successful_downloads > 0:
                msg = "ℹ Download stopped. Files completed before stopping: {}"
                GLib.idle_add(window.log_message, msg.format(successful_downloads))
                logger.info(f"Download stopped with {successful_downloads} files completed")
            else:
                GLib.idle_add(window.log_message, "ℹ Download stopped. No files were completed.")
                logger.info("Download stopped with no files completed")
            if skipped_downloads > 0:
                GLib.idle_add(window.log_message, "⏭ Skipped (already existed): {}".format(skipped_downloads))
            return

        if successful_downloads > 0:
            GLib.idle_add(window.progress_bar.set_fraction, 1.0)
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)

            if failed_downloads > 0:
                GLib.idle_add(window.progress_bar.set_text, "Completed with warnings")
                msg = "✓ Download completed: {} file(s) downloaded"
                GLib.idle_add(window.log_message, msg.format(successful_downloads))
                if skipped_downloads > 0:
                    msg = "⏭ Skipped (already existed): {}"
                    GLib.idle_add(window.log_message, msg.format(skipped_downloads))
                msg = "⚠ Warning: {} video(s) unavailable or failed"
                GLib.idle_add(window.log_message, msg.format(failed_downloads))
                logger.warning(
                    f"Download completed with {successful_downloads} successes, "
                    f"{skipped_downloads} skipped, {failed_downloads} failures"
                )

                if failed_videos:
                    GLib.idle_add(window.log_message, "")
                    GLib.idle_add(window.log_message, "Failed videos:")
                    GLib.idle_add(window.log_message, "-" * 60)
                    for i, failed in enumerate(failed_videos, 1):
                        GLib.idle_add(window.log_message, "{}. {}".format(i, failed['video_context']))
                        GLib.idle_add(window.log_message, "   Error: {}".format(failed['line']))
                    GLib.idle_add(window.log_message, "-" * 60)

                GLib.idle_add(
                    window.show_success_dialog,
                    "Download completed!\n\n✓ {} file(s) downloaded\n"
                    "⚠ {} video(s) unavailable".format(successful_downloads, failed_downloads)
                )
                GLib.idle_add(
                    window.send_notification,
                    "Download completed with warnings",
                    "{} file(s) downloaded, {} unavailable".format(
                        successful_downloads, failed_downloads
                    ),
                    "dialog-warning"
                )
            else:
                GLib.idle_add(window.progress_bar.set_text, "Completed!")
                msg = "✓ Download completed successfully: {} file(s)"
                GLib.idle_add(window.log_message, msg.format(successful_downloads))
                if skipped_downloads > 0:
                    msg = "⏭ Skipped (already existed): {}"
                    GLib.idle_add(window.log_message, msg.format(skipped_downloads))
                logger.info(
                    f"Download completed successfully: {successful_downloads} files, "
                    f"{skipped_downloads} skipped"
                )
                GLib.idle_add(
                    window.show_success_dialog,
                    "Download completed successfully!\n\n{} file(s) downloaded".format(
                        successful_downloads
                    )
                )
                GLib.idle_add(
                    window.send_notification,
                    "Download completed!",
                    "{} file(s) downloaded successfully".format(successful_downloads),
                    "emblem-default"
                )
        elif process.returncode == 0:
            GLib.idle_add(window.progress_bar.set_fraction, 1.0)
            GLib.idle_add(window.progress_bar.set_text, "Completed!")
            GLib.idle_add(window.log_message, "")
            GLib.idle_add(window.log_message, "=" * 60)
            GLib.idle_add(window.log_message, "✓ Process completed")
            logger.info("Process completed with return code 0 but no files downloaded")
            GLib.idle_add(window.show_success_dialog, "Process completed!")
            GLib.idle_add(
                window.send_notification,
                "Process completed",
                "The download process has finished",
                "dialog-information"
            )
        else:
            GLib.idle_add(window.progress_bar.set_text, "Error")
            GLib.idle_add(window.log_message, "")
            msg = "✗ Error: Could not download any files (code {})"
            GLib.idle_add(window.log_message, msg.format(process.returncode))
            logger.error(f"Download failed with return code {process.returncode}")
            GLib.idle_add(
                window.show_error_dialog,
                "Error: Could not download any files.\nCheck the log for more details."
            )

    except ValidationError as e:
        logger.error(f"Validation error in download: {e}")
        GLib.idle_add(window.log_message, "✗ Validation error: {}".format(str(e)))
        GLib.idle_add(window.show_error_dialog, "Validation error:\n{}".format(str(e)))
        GLib.idle_add(window.progress_bar.set_text, "Error")
    except DownloadError as e:
        logger.error(f"Download error: {e}")
        GLib.idle_add(window.log_message, "✗ Download error: {}".format(str(e)))
        GLib.idle_add(window.show_error_dialog, "Download error:\n{}".format(str(e)))
        GLib.idle_add(window.progress_bar.set_text, "Error")
    except Exception as e:
        logger.error(f"Unexpected error in download thread: {e}", exc_info=True)
        GLib.idle_add(window.log_message, "✗ Unexpected error: {}".format(str(e)))
        GLib.idle_add(window.show_error_dialog, "Unexpected error:\n{}".format(str(e)))
        GLib.idle_add(window.progress_bar.set_text, "Error")
    finally:
        with window.download_lock:
            window.current_process = None
        window.current_downloading_file = None
        window.current_download_original = None
        logger.debug("Download thread cleanup completed")

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


def cleanup_partial_files(window: YouTubeMp3Downloader) -> None:
    """Delete partial files left by yt-dlp when the download is stopped"""
    logger.info("Starting cleanup of partial files")
    try:
        files_deleted = 0
        with window.download_lock:
            targets = list(window.active_download_targets)

        logger.debug(f"Cleaning up {len(targets)} target(s)")

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
                    try:
                        if os.path.isfile(candidate):
                            os.remove(candidate)
                            filename = os.path.basename(candidate)
                            window.log_message("🗑 Deleted partial file: {}".format(filename))
                            logger.debug(f"Deleted: {filename}")
                            files_deleted += 1
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Could not delete {candidate}: {e}")
                        window.log_message("⚠ Could not delete {}: {}".format(os.path.basename(candidate), str(e)))

                # Clean up fragment files using glob
                for wildcard in [f"{base}.f*", f"{base}.fragment*", f"{base}.frag*"]:
                    try:
                        for candidate in glob.glob(wildcard):
                            try:
                                if os.path.isfile(candidate):
                                    os.remove(candidate)
                                    filename = os.path.basename(candidate)
                                    window.log_message("🗑 Deleted residual chunk: {}".format(filename))
                                    logger.debug(f"Deleted chunk: {filename}")
                                    files_deleted += 1
                            except (OSError, PermissionError) as e:
                                logger.warning(f"Could not delete chunk {candidate}: {e}")
                    except Exception as e:
                        logger.warning(f"Error globbing {wildcard}: {e}")

                # Clean up thumbnail files
                for thumbnail in [f"{base}.jpg", f"{base}.jpeg", f"{base}.png", f"{base}.webp"]:
                    try:
                        if os.path.isfile(thumbnail):
                            os.remove(thumbnail)
                            filename = os.path.basename(thumbnail)
                            window.log_message("🗑 Deleted residual thumbnail: {}".format(filename))
                            logger.debug(f"Deleted thumbnail: {filename}")
                            files_deleted += 1
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Could not delete thumbnail {thumbnail}: {e}")

                # Check for incomplete MP3 files
                mp3_candidate = f"{base}.mp3"
                try:
                    if os.path.isfile(mp3_candidate):
                        if os.path.getsize(mp3_candidate) < 1024:
                            os.remove(mp3_candidate)
                            filename = os.path.basename(mp3_candidate)
                            window.log_message("🗑 Deleted incomplete MP3: {}".format(filename))
                            logger.debug(f"Deleted incomplete MP3: {filename}")
                            files_deleted += 1
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not process MP3 {mp3_candidate}: {e}")

            except Exception as file_error:
                logger.error(f"Error cleaning target {target}: {file_error}")
                window.log_message("⚠ Could not clean {}: {}".format(os.path.basename(target), str(file_error)))

        with window.download_lock:
            for target in targets:
                window.active_download_targets.discard(target)

        if files_deleted > 0:
            window.log_message("✓ {} partial file(s) deleted".format(files_deleted))
            logger.info(f"Cleanup completed: {files_deleted} files deleted")
        else:
            window.log_message("ℹ No partial files found to delete")
            logger.info("Cleanup completed: no files to delete")

    except Exception as e:
        logger.error(f"Error in cleanup_partial_files: {e}", exc_info=True)
        window.log_message("⚠ Error cleaning partial files: {}".format(str(e)))
