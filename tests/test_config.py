"""Tests for youtubemp3downloader.config module."""

import json
import pytest

from youtubemp3downloader.config import load_config, save_config, _validate_config
from youtubemp3downloader.exceptions import ConfigurationError


class TestValidateConfig:
    """Tests for _validate_config function."""

    def test_valid_dict(self):
        result = _validate_config({"download_path": "/tmp", "use_youtube_auth": False})
        assert result == {"download_path": "/tmp", "use_youtube_auth": False}

    def test_empty_dict(self):
        result = _validate_config({})
        assert result == {}

    def test_non_dict_returns_empty(self):
        result = _validate_config("not a dict")
        assert result == {}

    def test_none_returns_empty(self):
        result = _validate_config(None)
        assert result == {}

    def test_list_returns_empty(self):
        result = _validate_config([1, 2, 3])
        assert result == {}


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_from_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({"download_path": "/tmp/music"}))

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("youtubemp3downloader.config.LEGACY_CONFIG_FILE", tmp_path / "nonexistent")

        result = load_config()
        assert result["download_path"] == "/tmp/music"

    def test_load_missing_file_returns_empty(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_dir / "config.json")
        monkeypatch.setattr("youtubemp3downloader.config.LEGACY_CONFIG_FILE", tmp_path / "nonexistent")

        result = load_config()
        assert result == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        config_file.write_text("{invalid json")

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("youtubemp3downloader.config.LEGACY_CONFIG_FILE", tmp_path / "nonexistent")

        result = load_config()
        assert result == {}

    def test_legacy_migration(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        legacy_file = tmp_path / "legacy.json"
        legacy_file.write_text(json.dumps({"download_path": "/old/path"}))

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("youtubemp3downloader.config.LEGACY_CONFIG_FILE", legacy_file)

        result = load_config()
        assert result["download_path"] == "/old/path"
        assert not legacy_file.exists()
        assert config_file.exists()


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_and_reload(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_file = config_dir / "config.json"

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)

        save_config({"download_path": "/tmp/test", "notifications_enabled": True})

        with open(config_file) as f:
            data = json.load(f)
        assert data["download_path"] == "/tmp/test"
        assert data["notifications_enabled"] is True

    def test_save_overwrites_existing(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({"old_key": "old_value"}))

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)

        save_config({"new_key": "new_value"})

        with open(config_file) as f:
            data = json.load(f)
        assert "old_key" not in data
        assert data["new_key"] == "new_value"

    def test_save_non_serializable_raises(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "youtube-mp3-downloader"
        config_file = config_dir / "config.json"

        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("youtubemp3downloader.config.CONFIG_FILE", config_file)

        with pytest.raises(ConfigurationError):
            save_config({"bad": set([1, 2, 3])})
