"""Probe a stratified sample of 50 image_urls to estimate the IG CDN expiry rate.

HEAD requests only — no image bytes downloaded.
Read-only on the parquet file.
"""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "df_master_masked_with_topics.parquet"

SAMPLE_SIZE = 50
PER_TYPE = {"photo": 17, "carousel": 17, "reel": 16}  # sums to 50
TIMEOUT = 8.0
MAX_WORKERS = 10
SEED = 42

# Realistic browser UA — IG CDN sometimes 403s python-requests
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}


def probe(url: str) -> dict:
    out = {
        "url": url,
        "status": None,
        "ok": False,
        "ctype": None,
        "clen": None,
        "error": None,
    }
    try:
        r = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        out["status"] = r.status_code
        out["ok"] = r.status_code == 200
        out["ctype"] = r.headers.get("Content-Type")
        cl = r.headers.get("Content-Length")
        out["clen"] = int(cl) if cl and cl.isdigit() else None
        # Some CDNs reject HEAD; fall back to GET range
        if r.status_code in (403, 405) and "head" in r.reason.lower() if r.reason else False:
            pass
    except requests.RequestException as e:
        out["error"] = type(e).__name__
    return out


def main() -> None:
    print(f"Loading: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH, columns=["post_id", "post_url", "image_url", "content_type"])
    df = df[df["image_url"].astype(str).str.len() > 0].copy()
    print(f"Posts with non-empty image_url: {len(df)}")

    rng = random.Random(SEED)
    sampled: list[tuple[str, str, str, str]] = []
    for ct, n in PER_TYPE.items():
        sub = df[df["content_type"] == ct]
        if len(sub) == 0:
            continue
        idxs = rng.sample(list(sub.index), k=min(n, len(sub)))
        for i in idxs:
            sampled.append(
                (
                    df.at[i, "post_id"],
                    df.at[i, "content_type"],
                    df.at[i, "post_url"],
                    df.at[i, "image_url"],
                )
            )

    print(f"Sampled {len(sampled)} URLs ({PER_TYPE}); SEED={SEED}\n")

    # Probe concurrently
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(probe, url): (pid, ct, purl, url) for (pid, ct, purl, url) in sampled}
        for fut in as_completed(futs):
            pid, ct, purl, url = futs[fut]
            r = fut.result()
            r["post_id"] = pid
            r["content_type"] = ct
            r["post_url"] = purl
            results.append(r)

    res_df = pd.DataFrame(results)

    print("=" * 72)
    print("STATUS CODE DISTRIBUTION")
    print("=" * 72)
    sc = res_df["status"].fillna("ERR").astype(str).value_counts(dropna=False)
    for k, v in sc.items():
        print(f"  HTTP {k:<5}: {v}")
    err = res_df["error"].dropna().value_counts()
    for k, v in err.items():
        print(f"  EXC  {k:<10}: {v}")

    print("\n" + "=" * 72)
    print("BY content_type")
    print("=" * 72)
    grp = res_df.groupby("content_type").agg(
        n=("ok", "size"),
        live=("ok", "sum"),
        median_kb=("clen", lambda s: round((s.dropna().median() or 0) / 1024, 1)),
    )
    grp["live_pct"] = (100 * grp["live"] / grp["n"]).round(1)
    print(grp[["n", "live", "live_pct", "median_kb"]].to_string())

    print("\n" + "=" * 72)
    print("CONTENT-TYPE / SIZE (live URLs only)")
    print("=" * 72)
    live = res_df[res_df["ok"]]
    if len(live):
        ct_counts = live["ctype"].fillna("?").value_counts()
        for k, v in ct_counts.items():
            print(f"  {k:<30}: {v}")
        sizes_kb = (live["clen"].dropna() / 1024).describe().round(1)
        print("\n  Content-Length (KB) stats on live URLs:")
        print(sizes_kb.to_string())
    else:
        print("  No live URLs in sample.")

    print("\n" + "=" * 72)
    print("FAILURE EXAMPLES (up to 5)")
    print("=" * 72)
    failed = res_df[~res_df["ok"]].head(5)
    for _, r in failed.iterrows():
        print(
            f"  [{r['content_type']:<8}] status={r['status']} err={r['error']} "
            f"post={r['post_url']}"
        )
        host = urlparse(r["url"]).netloc
        print(f"      host: {host}")

    overall_live_pct = 100.0 * res_df["ok"].sum() / len(res_df)
    print("\n" + "=" * 72)
    print(f"OVERALL: {res_df['ok'].sum()}/{len(res_df)} live ({overall_live_pct:.1f}%)")
    print("=" * 72)

    # Extrapolation
    n_total = len(df)  # 4127 with non-empty image_url
    est_live = int(round(n_total * overall_live_pct / 100.0))
    est_kb = live["clen"].dropna().median() if len(live) else None
    if est_kb:
        est_total_mb = est_live * est_kb / 1024 / 1024
        print(f"\nExtrapolation to {n_total} posts:")
        print(f"  Estimated live: ~{est_live}")
        print(f"  Estimated total size: ~{est_total_mb:.0f} MB at native res")


if __name__ == "__main__":
    main()
