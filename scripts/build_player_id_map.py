"""Create a compact MLBAM-to-FanGraphs player ID map from Chadwick Register shards."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    shards = sorted((args.register / "data").glob("people-*.csv"))
    if not shards:
        raise SystemExit("No Chadwick people shards were found.")
    frames = [
        pd.read_csv(
            shard,
            usecols=["key_mlbam", "key_fangraphs", "name_first", "name_last"],
            low_memory=False,
        )
        for shard in shards
    ]
    people = pd.concat(frames, ignore_index=True)
    people["key_mlbam"] = pd.to_numeric(people["key_mlbam"], errors="coerce")
    people["key_fangraphs"] = pd.to_numeric(people["key_fangraphs"], errors="coerce")
    people = people.dropna(subset=["key_mlbam", "key_fangraphs"]).copy()
    people["key_mlbam"] = people["key_mlbam"].astype(int)
    people["key_fangraphs"] = people["key_fangraphs"].astype(int)
    people = people.drop_duplicates("key_mlbam", keep="last").sort_values("key_mlbam")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    people.to_csv(args.output, index=False, compression="gzip")
    print(f"Wrote {len(people):,} cross-source player IDs.")


if __name__ == "__main__":
    main()
