"""
Custom exception classes for YouTube MP3 Downloader.

This module defines specific exception types for better error categorization
and handling throughout the application.
"""


class YouTubeMp3DownloaderError(Exception):
    """Base exception for all YouTube MP3 Downloader errors."""
    pass


class ConfigurationError(YouTubeMp3DownloaderError):
    """Exception raised for configuration loading/saving issues."""
    pass


class DependencyError(YouTubeMp3DownloaderError):
    """Exception raised when required dependencies are missing."""
    
    def __init__(self, missing_deps):
        """
        Initialize DependencyError.
        
        Args:
            missing_deps: List of missing dependency names or a single dependency name
        """
        if isinstance(missing_deps, str):
            missing_deps = [missing_deps]
        self.missing_deps = missing_deps
        deps_str = ", ".join(missing_deps)
        super().__init__(f"Missing required dependencies: {deps_str}")


class DownloadError(YouTubeMp3DownloaderError):
    """Exception raised when download operations fail."""
    pass


class ValidationError(YouTubeMp3DownloaderError):
    """Exception raised for invalid URLs, paths, or other validation failures."""
    pass
