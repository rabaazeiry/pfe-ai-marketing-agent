"""CLI entrypoint: build the master corpus and write it to ml-service/data/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from corpus.config import MONGODB_URI  # noqa: E402
from corpus.loader import build_master_corpus, save_master_corpus  # noqa: E402
from corpus.mongo import (  # noqa: E402
    fetch_active_competitors,
    fetch_instagram_analyses,
    fetch_pfe_projects,
    get_client,
    get_database,
)
from corpus.stats import print_stats  # noqa: E402


def main() -> None:
    print(f"Connecting to MongoDB ({MONGODB_URI}) ...")
    client = get_client()
    db = get_database(client)
    print(f"Connected. Database: {db.name}")

    projects = fetch_pfe_projects(db)
    project_ids = [p["_id"] for p in projects]
    print(f"  PFE projects:        {len(projects)}")

    competitors = fetch_active_competitors(db, project_ids)
    competitor_ids = [c["_id"] for c in competitors]
    print(f"  Active competitors:  {len(competitors)}")

    analyses = fetch_instagram_analyses(db, competitor_ids)
    print(f"  Instagram analyses:  {len(analyses)}")

    df, drop_log, medians = build_master_corpus(projects, competitors, analyses)
    print(f"  Drop log:            {drop_log}")
    print(f"  Industry medians (cold-start prior, Trivedi 2019 / Chen 2022):")
    for ind, m in medians.items():
        print(f"    {ind:<14} engagement_rate={m['engagement_rate']:.4f}  "
              f"likes={m['likes']:.1f}")

    out_dir = ROOT / "data"
    csv_path, parquet_path = save_master_corpus(df, out_dir)

    print_stats(df, csv_path, parquet_path)

    client.close()


if __name__ == "__main__":
    main()
