
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Gio
import subprocess
import threading
import os
import re
import shutil
from pathlib import Path

from . import config
from . import utils
from . import download
from .exceptions import ValidationError
from .logger import get_logger

logger = get_logger(__name__)
class YouTubeMp3Downloader(Gtk.Window):
    def __init__(self):
        super().__init__(title="YouTube MP3 Downloader")
        self.set_border_width(10)

        # Load persistent configuration
        self.config = config.load_config()

        # Default download directory (or loaded from config)
        self.download_path = self.config.get('download_path', str(Path.home() / "Downloads"))

        # YouTube authentication status (loaded from config)
        self.use_youtube_auth = self.config.get('use_youtube_auth', False)

        # Notification status (loaded from config)
        self.notifications_enabled = self.config.get('notifications_enabled', True)

        # Current download process
        self.current_process = None
        self.download_stopped = False
        self.download_cancel_requested = False  # Flag to cancel before the process starts
        self.current_downloading_file = None
        self.current_download_original = None
        self.download_lock = threading.Lock()
        self.active_download_targets = set()

        # Apply saved window size
        window_width = self.config.get('window_width', 600)
        window_height = self.config.get('window_height', 400)
        self.set_default_size(window_width, window_height)

        # Apply saved window position (if it exists)
        if 'window_x' in self.config and 'window_y' in self.config:
            self.move(self.config['window_x'], self.config['window_y'])
            # Do not center if we already have a saved position
        else:
            self.set_position(Gtk.WindowPosition.CENTER)

        # Connect close event to save configuration
        self.connect("delete-event", self.on_delete_event)

        # Create HeaderBar
        self.setup_headerbar()

        # Create interface
        self.setup_ui()

    def setup_headerbar(self):
        """Set up the top bar with a menu"""
        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(True)
        headerbar.props.title = "YouTube MP3 Downloader"
        self.set_titlebar(headerbar)

        # Hamburger menu button
        menu_button = Gtk.MenuButton()
        menu_icon = Gio.ThemedIcon(name="open-menu-symbolic")
        menu_image = Gtk.Image.new_from_gicon(menu_icon, Gtk.IconSize.BUTTON)
        menu_button.add(menu_image)
        menu_button.set_tooltip_text("Menu")

        # Create the menu
        menu = Gio.Menu()

        # Preferences section
        preferences_menu = Gio.Menu()
        preferences_menu.append("Enable notifications", "app.toggle-notifications")
        menu.append_section("Preferences", preferences_menu)

        # Set up the menu popover
        popover = Gtk.Popover.new_from_model(menu_button, menu)
        menu_button.set_popover(popover)

        # Add the menu button to the right side of the headerbar
        headerbar.pack_end(menu_button)

    def setup_ui(self):
        # Main vertical box
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Title
        title_label = Gtk.Label()
        title_label.set_markup("<big><b>YouTube MP3 Downloader</b></big>\n<small>Supports individual videos and playlists</small>")
        vbox.pack_start(title_label, False, False, 5)

        # Separator
        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        # URL Input
        url_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        url_label = Gtk.Label(label="YouTube URL:")
        url_label.set_size_request(120, -1)
        url_label.set_xalign(0)
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("YouTube video or playlist URL...")
        self.url_entry.connect("changed", self.on_url_changed)

        # Button to clear URL
        self.clear_url_button = Gtk.Button()
        clear_url_icon = Gio.ThemedIcon(name="edit-clear-symbolic")
        clear_url_image = Gtk.Image.new_from_gicon(clear_url_icon, Gtk.IconSize.BUTTON)
        self.clear_url_button.add(clear_url_image)
        self.clear_url_button.set_tooltip_text("Clear URL")
        self.clear_url_button.connect("clicked", self.on_clear_url_clicked)

        # Button to paste URL
        self.paste_url_button = Gtk.Button()
        paste_url_icon = Gio.ThemedIcon(name="edit-paste-symbolic")
        paste_url_image = Gtk.Image.new_from_gicon(paste_url_icon, Gtk.IconSize.BUTTON)
        self.paste_url_button.add(paste_url_image)
        self.paste_url_button.set_tooltip_text("Paste URL from clipboard")
        self.paste_url_button.connect("clicked", self.on_paste_url_clicked)

        # URL validation indicator
        self.url_status_label = Gtk.Label()
        self.url_status_label.set_text("")
        self.url_status_label.set_size_request(20, -1)

        url_box.pack_start(url_label, False, False, 0)
        url_box.pack_start(self.url_entry, True, True, 0)
        url_box.pack_start(self.paste_url_button, False, False, 0) # Add paste button
        url_box.pack_start(self.clear_url_button, False, False, 0)
        url_box.pack_start(self.url_status_label, False, False, 0)
        vbox.pack_start(url_box, False, False, 0)

        # YouTube authentication checkbox
        self.auth_checkbox = Gtk.CheckButton(label="🔐 Use YouTube authentication (for private playlists)")
        self.auth_checkbox.set_tooltip_text("Uses Firefox cookies to access private playlists. Make sure you are logged into YouTube in Firefox.")
        self.auth_checkbox.set_active(self.use_youtube_auth)  # Apply loaded value
        self.auth_checkbox.connect("toggled", self.on_auth_toggled)
        vbox.pack_start(self.auth_checkbox, False, False, 0)

        # Destination folder
        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        folder_label = Gtk.Label(label="Destination folder:")
        folder_label.set_size_request(120, -1)
        folder_label.set_xalign(0)
        self.folder_entry = Gtk.Entry()
        self.folder_entry.set_text(self.download_path)
        self.folder_entry.set_editable(False)
        self.folder_button = Gtk.Button(label="Select...")
        self.folder_button.connect("clicked", self.on_select_folder)

        # Button to open folder
        self.open_folder_button = Gtk.Button()
        open_folder_icon = Gio.ThemedIcon(name="folder-open-symbolic")
        open_folder_image = Gtk.Image.new_from_gicon(open_folder_icon, Gtk.IconSize.BUTTON)
        self.open_folder_button.add(open_folder_image)
        self.open_folder_button.set_tooltip_text("Open destination folder")
        self.open_folder_button.connect("clicked", self.on_open_folder)

        folder_box.pack_start(folder_label, False, False, 0)
        folder_box.pack_start(self.folder_entry, True, True, 0)
        folder_box.pack_start(self.folder_button, False, False, 0)
        folder_box.pack_start(self.open_folder_button, False, False, 0)
        vbox.pack_start(folder_box, False, False, 0)

        # Download and stop buttons
        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.download_button = Gtk.Button(label="⬇ Download MP3 (320kbps)")
        self.download_button.connect("clicked", self.on_download_clicked)
        self.download_button.get_style_context().add_class("suggested-action")  # Always visible

        self.stop_button = Gtk.Button(label="⏹ Stop")
        self.stop_button.connect("clicked", self.on_stop_clicked)
        # Do not add "destructive-action" at the beginning because it is disabled
        self.stop_button.set_sensitive(False)  # Initially disabled

        buttons_box.pack_start(self.download_button, True, True, 0)
        buttons_box.pack_start(self.stop_button, True, True, 0)
        vbox.pack_start(buttons_box, False, False, 5)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text("Waiting...")
        vbox.pack_start(self.progress_bar, False, False, 0)

        # Log/status area
        log_label = Gtk.Label(label="Log:")
        log_label.set_xalign(0)
        vbox.pack_start(log_label, False, False, 0)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.log_buffer = self.log_view.get_buffer()
        scrolled_window.add(self.log_view)
        vbox.pack_start(scrolled_window, True, True, 0)

        # Button to copy log (only visible when finished)
        self.copy_log_button = Gtk.Button(label="📋 Copy full log")
        self.copy_log_button.connect("clicked", self.on_copy_log_clicked)
        self.copy_log_button.set_no_show_all(True)  # Do not show by default
        self.copy_log_button.hide()  # Initially hidden
        vbox.pack_start(self.copy_log_button, False, False, 5)

    def _set_ui_sensitive(self, sensitive):
        """Sets the sensitivity of UI elements that should be disabled during download."""
        self.url_entry.set_sensitive(sensitive)
        self.auth_checkbox.set_sensitive(sensitive)
        # Find the folder_button and open_folder_button by their names or by iterating
        # For now, let's assume we can access them directly if they were stored as attributes
        # Or, we can make them attributes if they are not already.
        # For simplicity, I'll make them attributes now.
        self.folder_button.set_sensitive(sensitive)
        self.open_folder_button.set_sensitive(sensitive)
        self.clear_url_button.set_sensitive(sensitive)
        self.paste_url_button.set_sensitive(sensitive)

    def on_paste_url_clicked(self, button):
        """Paste URL from clipboard"""
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            text = clipboard.wait_for_text()
            if text:
                self.url_entry.set_text(text)
                self.url_entry.grab_focus()
                logger.debug("URL pasted from clipboard")
            else:
                logger.debug("Clipboard is empty")
        except Exception as e:
            logger.error(f"Failed to paste from clipboard: {e}")
            self.show_error_dialog(f"Could not paste from clipboard:\n{str(e)}")

    def on_select_folder(self, button):
        """Open dialog to select folder"""
        try:
            dialog = Gtk.FileChooserDialog(
                title="Select destination folder",
                parent=self,
                action=Gtk.FileChooserAction.SELECT_FOLDER
            )
            dialog.add_buttons(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OPEN, Gtk.ResponseType.OK
            )
            
            # Try to set current folder, but don't fail if it doesn't exist
            try:
                if os.path.isdir(self.download_path):
                    dialog.set_current_folder(self.download_path)
            except (OSError, TypeError) as e:
                logger.warning(f"Could not set current folder in dialog: {e}")

            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                self.download_path = dialog.get_filename()
                self.folder_entry.set_text(self.download_path)
                # Save download path in configuration
                self.config['download_path'] = self.download_path
                try:
                    config.save_config(self.config)
                    logger.info(f"Download path updated: {self.download_path}")
                except Exception as e:
                    logger.error(f"Failed to save download path: {e}")

            dialog.destroy()
        except Exception as e:
            logger.error(f"Error in folder selection dialog: {e}")
            self.show_error_dialog(f"Could not open folder selection dialog:\n{str(e)}")

    def on_open_folder(self, button):
        """Open destination folder in the file explorer"""
        try:
            # Validate that the folder exists
            if not os.path.isdir(self.download_path):
                logger.warning(f"Download folder does not exist: {self.download_path}")
                self.show_error_dialog(f"Folder does not exist:\n{self.download_path}")
                return
            
            # Check if xdg-open is available
            if shutil.which("xdg-open"):
                subprocess.Popen(
                    ["xdg-open", self.download_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.debug(f"Opened folder: {self.download_path}")
            else:
                logger.error("xdg-open not found")
                self.show_error_dialog(
                    "Cannot open folder: xdg-open is not installed.\n"
                    f"Folder path: {self.download_path}"
                )
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to open folder with xdg-open: {e}")
            self.show_error_dialog(f"Could not open folder:\n{str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error opening folder: {e}")
            self.show_error_dialog(f"Could not open folder:\n{str(e)}")

    def on_url_changed(self, entry):
        """Validate URL in real time and update visual indicator"""
        url = entry.get_text().strip()

        if not url:
            # Empty field
            self.url_status_label.set_text("")
            self.url_status_label.set_tooltip_text("")
            return

        try:
            url_type, _ = utils.classify_youtube_url(url)

            if url_type:
                self.url_status_label.set_markup("<span foreground='green' size='large'>✓</span>")
                self.url_status_label.set_tooltip_text("Valid YouTube URL ({})".format(url_type))
            else:
                self.url_status_label.set_markup("<span foreground='red' size='large'>✗</span>")
                self.url_status_label.set_tooltip_text("Invalid YouTube URL")
        except ValidationError as e:
            logger.error(f"Validation error in URL check: {e}")
            self.url_status_label.set_markup("<span foreground='red' size='large'>✗</span>")
            self.url_status_label.set_tooltip_text("Invalid input")
        except Exception as e:
            logger.error(f"Unexpected error validating URL: {e}")

    def on_clear_url_clicked(self, button):
        """Clear the URL field"""
        self.url_entry.set_text("")
        self.url_entry.grab_focus()

    def on_auth_toggled(self, checkbox):
        """Update authentication status when the checkbox is changed"""
        try:
            self.use_youtube_auth = checkbox.get_active()
            # Save authentication status in configuration
            self.config['use_youtube_auth'] = self.use_youtube_auth
            config.save_config(self.config)
            logger.info(f"YouTube authentication {'enabled' if self.use_youtube_auth else 'disabled'}")
        except Exception as e:
            logger.error(f"Failed to save authentication setting: {e}")

    def on_delete_event(self, widget, event):
        """Save window configuration before closing"""
        try:
            # Get current window size
            width, height = self.get_size()
            self.config['window_width'] = width
            self.config['window_height'] = height

            # Get current window position
            x, y = self.get_position()
            self.config['window_x'] = x
            self.config['window_y'] = y

            # Save configuration
            config.save_config(self.config)
            logger.info("Window configuration saved")
        except Exception as e:
            logger.error(f"Failed to save window configuration: {e}")

        # Return False to allow the window to close normally
        return False

    def send_notification(self, title, message, icon="dialog-information"):
        """Send system notification if enabled"""
        if not self.notifications_enabled:
            logger.debug("Notifications disabled, skipping")
            return

        # Try Gio.Notification first (native GTK)
        try:
            notification = Gio.Notification.new(title)
            notification.set_body(message)

            # Set icon
            if icon == "dialog-information":
                notification.set_icon(Gio.ThemedIcon.new("dialog-information"))
            elif icon == "dialog-warning":
                notification.set_icon(Gio.ThemedIcon.new("dialog-warning"))
            elif icon == "emblem-default":
                notification.set_icon(Gio.ThemedIcon.new("emblem-default"))

            # Send notification through the application
            app = self.get_application()
            if app:
                app.send_notification(None, notification)
                logger.debug(f"Notification sent via Gio: {title}")
                return
        except Exception as e:
            logger.debug(f"Gio notification failed: {e}")

        # Fallback: use notify-send if available
        if shutil.which("notify-send"):
            try:
                subprocess.run([
                    "notify-send",
                    "-a", "YouTube MP3 Downloader",
                    "-i", icon,
                    title,
                    message
                ], check=False, timeout=5, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL)
                logger.debug(f"Notification sent via notify-send: {title}")
                return
            except subprocess.TimeoutExpired:
                logger.warning("notify-send timed out")
            except subprocess.SubprocessError as e:
                logger.warning(f"notify-send failed: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error with notify-send: {e}")
        else:
            logger.debug("notify-send not available")
        
        # Silent fail - notifications are optional
        logger.debug("All notification methods failed, continuing without notification")

    def on_copy_log_clicked(self, button):
        """Copy all log content to the clipboard"""
        try:
            # Get all text from the buffer
            start_iter = self.log_buffer.get_start_iter()
            end_iter = self.log_buffer.get_end_iter()
            log_text = self.log_buffer.get_text(start_iter, end_iter, True)

            # Copy to clipboard
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(log_text, -1)
            clipboard.store()

            # Show confirmation in the log
            self.log_message("")
            self.log_message("✓ Log copied to clipboard")
            logger.debug("Log copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy log to clipboard: {e}")
            self.show_error_dialog(f"Could not copy log:\n{str(e)}")

    def on_stop_clicked(self, button):
        """Stop the current download process"""
        self.log_message("")
        self.log_message("⏹ Stopping download...")
        logger.info("User requested download stop")

        # Mark as stopped and request cancellation
        self.download_stopped = True
        self.download_cancel_requested = True

        # If there is a running process, terminate it
        if self.current_process:
            try:
                self.current_process.terminate()  # Try to terminate gracefully
                logger.debug("Sent terminate signal to download process")
                # Give time to terminate gracefully
                try:
                    self.current_process.wait(timeout=2)
                    logger.debug("Download process terminated gracefully")
                except subprocess.TimeoutExpired:
                    # If it does not terminate in 2 seconds, force termination
                    self.log_message("⚠ Forcing process termination...")
                    logger.warning("Process did not terminate, forcing kill")
                    self.current_process.kill()
                    self.current_process.wait()
                    logger.info("Download process killed")

                # Clean up partial files
                download.cleanup_partial_files(self)

                self.progress_bar.set_text("Stopped")
                self.progress_bar.set_fraction(0.0)
                self.log_message("✓ Download stopped by user")
            except subprocess.SubprocessError as e:
                logger.error(f"Error stopping download process: {e}")
                self.log_message("✗ Error stopping: {}".format(str(e)))
            except Exception as e:
                logger.error(f"Unexpected error stopping download: {e}")
                self.log_message("✗ Error stopping: {}".format(str(e)))
        else:
            # There is no process yet, but cancellation is requested
            # The thread will detect it and stop
            self.log_message("✓ Cancellation requested")
            self.progress_bar.set_text("Cancelled")
            self.progress_bar.set_fraction(0.0)
            logger.info("Download cancellation requested (no process running)")

    def log_message(self, message):
        """Add message to the log area"""
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, message + "\n")
        # Auto-scroll to the end
        mark = self.log_buffer.create_mark(None, end_iter, False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def on_download_clicked(self, button):
        """Start download"""
        url = self.url_entry.get_text().strip()
        
        logger.info("Download button clicked")

        if not url:
            logger.warning("Empty URL provided")
            self.show_error_dialog("Please enter a YouTube URL")
            return

        try:
            url_type, match = utils.classify_youtube_url(url)
        except ValidationError as e:
            logger.error(f"URL validation error: {e}")
            self.show_error_dialog(f"Invalid input:\n{str(e)}")
            return
        except Exception as e:
            logger.error(f"Unexpected error validating URL: {e}")
            self.show_error_dialog(f"Error validating URL:\n{str(e)}")
            return

        if not url_type:
            # Specific error messages depending on the problem
            if "youtube.com" in url or "youtu.be" in url:
                if "/watch?v=" in url and len(re.findall(r'v=([\w-]+)', url)) > 0:
                    video_id = re.findall(r'v=([\w-]+)', url)[0]
                    if len(video_id) != 11:
                        logger.warning(f"Invalid video ID length: {video_id} ({len(video_id)} chars)")
                        self.show_error_dialog("Invalid video ID length.\nYouTube video IDs must be exactly 11 characters.\nFound: {} ({} characters)".format(video_id, len(video_id)))
                        return
                logger.warning(f"Invalid YouTube URL format: {url}")
                self.show_error_dialog("Invalid YouTube URL format.\n\nValid formats:\n• youtube.com/watch?v=VIDEO_ID (11 chars)\n• youtu.be/VIDEO_ID\n• youtube.com/playlist?list=PLAYLIST_ID\n• youtube.com/shorts/VIDEO_ID")
            else:
                logger.warning(f"Not a YouTube URL: {url}")
                self.show_error_dialog("This doesn't appear to be a YouTube URL.\nPlease enter a valid YouTube video or playlist URL.")
            return

        logger.info(f"Valid {url_type} URL: {url}")

        # Validate and normalize the destination folder
        try:
            download_dir = Path(self.download_path).expanduser().resolve()
            download_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Download directory prepared: {download_dir}")
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to prepare destination folder: {e}")
            self.show_error_dialog("Could not prepare destination folder:\n{}".format(str(e)))
            return
        except Exception as e:
            logger.error(f"Unexpected error with destination folder: {e}")
            self.show_error_dialog("Error with destination folder:\n{}".format(str(e)))
            return

        if not os.access(str(download_dir), os.W_OK | os.X_OK):
            logger.error(f"Destination folder not writable: {download_dir}")
            self.show_error_dialog("Destination folder is not writable:\n{}".format(str(download_dir)))
            return

        self.download_path = str(download_dir)
        self.folder_entry.set_text(self.download_path)

        # Reset download status
        self.download_stopped = False
        self.download_cancel_requested = False
        self.current_downloading_file = None
        self.current_download_original = None

        use_auth = self.use_youtube_auth

        # Disable UI elements
        self._set_ui_sensitive(False)

        # Disable download button and enable stop button
        self.download_button.set_sensitive(False)
        self.download_button.get_style_context().remove_class("suggested-action")
        self.stop_button.set_sensitive(True)
        self.stop_button.get_style_context().add_class("destructive-action")
        self.progress_bar.set_text("Downloading...")
        self.progress_bar.set_fraction(0.0)

        # Clear log and hide copy button
        self.log_buffer.set_text("")
        self.copy_log_button.hide()

        self.log_message("Starting download of: {}".format(url))
        self.log_message("Destination: {}".format(self.download_path))
        self.log_message("-" * 60)
        logger.info(f"Starting download thread for {url_type}")

        # Run download in a separate thread
        try:
            thread = threading.Thread(
                target=download.download_thread,
                args=(self, url, url_type, self.download_path, use_auth)
            )
            thread.daemon = True
            thread.start()
            logger.debug("Download thread started")
        except Exception as e:
            logger.error(f"Failed to start download thread: {e}")
            self.show_error_dialog(f"Could not start download:\n{str(e)}")
            # Restore UI
            self._set_ui_sensitive(True)
            self.download_button.set_sensitive(True)
            self.download_button.get_style_context().add_class("suggested-action")
            self.stop_button.set_sensitive(False)
            self.stop_button.get_style_context().remove_class("destructive-action")

    def show_error_dialog(self, message):
        """Show error dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error"
        )
        dialog.format_secondary_text(message)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def show_success_dialog(self, message):
        """Show success dialog"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Success"
        )
        dialog.format_secondary_text(message)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
