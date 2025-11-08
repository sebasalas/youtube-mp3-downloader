
import json
from pathlib import Path

# Configuration file location
CONFIG_DIR = Path.home() / ".config" / "youtube-mp3-downloader"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_CONFIG_FILE = Path.home() / ".youtube-mp3-downloader-config.json"


def load_config():
    """Load configuration from JSON file"""
    # Create config directory if it doesn't exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check for legacy config file and migrate
    if LEGACY_CONFIG_FILE.exists() and not CONFIG_FILE.exists():
        try:
            import shutil
            shutil.move(str(LEGACY_CONFIG_FILE), str(CONFIG_FILE))
        except Exception:
            pass
    
    # Load config
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Return default config
    return {}

def save_config(config):
    """Save configuration to JSON file"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass
