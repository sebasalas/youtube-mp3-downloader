
import sys
import shutil

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio

from .app_window import YouTubeMp3Downloader
from . import config

def check_dependencies():
    """Check for required command-line tools."""
    missing_deps = []
    if not shutil.which("yt-dlp"):
        missing_deps.append("yt-dlp")
    if not shutil.which("ffmpeg"):
        missing_deps.append("ffmpeg")

    if missing_deps:
        dialog = Gtk.MessageDialog(
            transient_for=None,
            modal=True,
            destroy_with_parent=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Missing Dependencies"
        )
        missing_str = "\n".join(missing_deps)
        dialog.format_secondary_text(
            "The following required tools are not installed or not in your PATH:\n\n"
            f"{missing_str}\n\n"
            "Please install them to continue."
        )
        dialog.run()
        dialog.destroy()
        sys.exit(1)
    return True


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.github.youtube-mp3-downloader")
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = YouTubeMp3Downloader()
            self.window.set_application(self)
            self.add_window(self.window)

            # Action for toggling notifications
            toggle_notifications_action = Gio.SimpleAction.new_stateful(
                "toggle-notifications",
                None,
                GLib.Variant.new_boolean(self.window.notifications_enabled)
            )
            toggle_notifications_action.connect("activate", self.on_toggle_notifications)
            self.add_action(toggle_notifications_action)

        self.window.show_all()

    def on_toggle_notifications(self, action, parameter):
        """Handle notification toggle"""
        # Change the state
        current_state = action.get_state().get_boolean()
        new_state = not current_state
        action.set_state(GLib.Variant.new_boolean(new_state))

        # Update in the window
        self.window.notifications_enabled = new_state

        # Save to configuration
        self.window.config['notifications_enabled'] = new_state
        config.save_config(self.window.config)

def main():
    # Check dependencies before starting the app
    check_dependencies()
    
    app = Application()
    return app.run(sys.argv)
