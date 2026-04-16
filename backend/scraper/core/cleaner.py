"""HTML stripping and noise filtering for raw scraped content."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core.types import RawPost

_WS_RE = re.compile(r"\s+")
_EMOJI_ONLY_RE = re.compile(r"^[\W_]+$")


def strip_html(raw: RawPost) -> str:
    """Return plain text extracted from a RawPost's HTML body.

    Strips <script>/<style>/<noscript> tags and collapses whitespace.
    """
    if not raw.raw_html:
        return ""
    soup = BeautifulSoup(raw.raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _WS_RE.sub(" ", soup.get_text(" ")).strip()


def is_noise(text: str) -> bool:
    """Return True if the text should be dropped before normalization."""
    if not text or len(text) < 3:
        return True
    return bool(_EMOJI_ONLY_RE.match(text))
