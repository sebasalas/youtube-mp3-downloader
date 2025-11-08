import re
from typing import Optional, Tuple

# Precompiled patterns to validate and classify YouTube URLs
YOUTUBE_PATTERNS = [
    (re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([\w-]{11})'), "Video"),
    (re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([\w-]{13,})'), "Playlist"),
    (re.compile(r'(?:https?://)?youtu\.be/([\w-]{11})'), "Video"),
    (re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([\w-]{11})'), "Short"),
]


def classify_youtube_url(url: str) -> Tuple[Optional[str], Optional[re.Match]]:
    """Return (type, match) for a YouTube URL or (None, None) if invalid."""
    cleaned_url = url.strip()
    for pattern, url_type in YOUTUBE_PATTERNS:
        match = pattern.match(cleaned_url)
        if match:
            return url_type, match
    return None, None