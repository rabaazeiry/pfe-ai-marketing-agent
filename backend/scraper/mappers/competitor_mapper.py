"""Shape NormalizedPost data into a Competitor.socialMedia update payload."""

from __future__ import annotations

from typing import Iterable

from core.types import NormalizedPost


def to_social_handle_updates(posts: Iterable[NormalizedPost]) -> dict:
    """Aggregate posts per platform for the existing Competitor model.

    Returns a dict keyed by platform; the Node backend merges this into
    Competitor.socialMedia without introducing a new collection.
    """
    by_platform: dict[str, dict] = {}
    for p in posts:
        bucket = by_platform.setdefault(
            p.platform, {"posts": 0, "likes": 0, "comments": 0}
        )
        bucket["posts"] += 1
        bucket["likes"] += p.likes
        bucket["comments"] += p.comments
    return by_platform
