"""Optional mapper: turn NormalizedPost data into seed content for Insight."""

from __future__ import annotations

from typing import Iterable, Optional

from core.types import NormalizedPost


def to_insight_seed(
    project_id: str, posts: Iterable[NormalizedPost]
) -> Optional[dict]:
    """Produce a lightweight payload the Node backend can feed to the LLM.

    The real Insight document is still created server-side; this mapper
    just extracts the signals (top posts, volume) without introducing a
    new Mongo model.
    """
    posts = list(posts)
    if not posts:
        return None

    top = sorted(posts, key=lambda p: p.likes + p.comments, reverse=True)[:5]
    return {
        "project": project_id,
        "postsConsidered": len(posts),
        "highlights": [
            {"url": p.url, "text": p.text[:240], "likes": p.likes, "comments": p.comments}
            for p in top
        ],
    }
