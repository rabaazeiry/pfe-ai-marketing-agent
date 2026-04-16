"""Shape NormalizedPost data into a SocialAnalysis document payload."""

from __future__ import annotations

from typing import Iterable

from core.types import NormalizedPost


def to_social_analysis_payload(
    competitor_id: str, posts: Iterable[NormalizedPost]
) -> dict:
    """Build the payload the Node backend inserts into SocialAnalysis."""
    posts = list(posts)
    return {
        "competitor": competitor_id,
        "postsCount": len(posts),
        "totalLikes": sum(p.likes for p in posts),
        "totalComments": sum(p.comments for p in posts),
        "languages": sorted({p.language for p in posts if p.language}),
        "samples": [
            {
                "url": p.url,
                "text": p.text[:280],
                "likes": p.likes,
                "comments": p.comments,
            }
            for p in posts[:20]
        ],
    }
