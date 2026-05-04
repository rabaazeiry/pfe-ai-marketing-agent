"""CLI entrypoint: clean df_master.parquet and write df_master_clean.{parquet,csv}."""
from __future__ import annotations

import sys
from pathlib import Path

# Force UTF-8 stdout so Arabic / emoji in sample-pair output don't crash
# the default Windows cp1252 console.
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from corpus.cleaner import (  # noqa: E402
    clean_master_corpus,
    print_clean_stats,
    save_master_corpus_clean,
)


def main() -> None:
    in_path = ROOT / "data" / "df_master.parquet"
    print(f"Loading {in_path} ...")
    df_before = pd.read_parquet(in_path)
    print(f"  Loaded: {len(df_before):,} rows, {len(df_before.columns)} cols")

    df_after, log = clean_master_corpus(df_before)
    print(f"  Drop log: {log}")

    out_dir = ROOT / "data"
    csv_path, parquet_path = save_master_corpus_clean(df_after, out_dir)

    print_clean_stats(df_before, df_after, log, csv_path, parquet_path)


if __name__ == "__main__":
    main()
