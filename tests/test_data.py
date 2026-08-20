from __future__ import annotations

import pandas as pd

from src.data import career_summary, filter_home_runs, normalize_home_runs
from src.demo import make_demo_home_runs


def test_demo_normalizes_and_orders_home_runs() -> None:
    raw = make_demo_home_runs(n=40, seed=12)
    cleaned = normalize_home_runs(raw.sample(frac=1, random_state=5))

    assert len(cleaned) == 40
    assert cleaned["home_run_number"].tolist() == list(range(1, 41))
    assert cleaned["game_date"].is_monotonic_increasing
    assert cleaned["home_run_distance"].notna().all()
    assert cleaned["launch_speed"].notna().all()
    assert cleaned["launch_angle"].notna().all()
    assert cleaned["matchup"].str.contains(" @ ").all()


def test_duplicate_event_is_removed() -> None:
    raw = make_demo_home_runs(n=8, seed=2)
    duplicated = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    cleaned = normalize_home_runs(duplicated)
    assert len(cleaned) == 8


def test_empty_filters_remove_all_rows() -> None:
    cleaned = normalize_home_runs(make_demo_home_runs(n=12, seed=3))
    assert filter_home_runs(cleaned, seasons=[], teams=[]).empty


def test_career_summary_uses_home_run_metrics() -> None:
    cleaned = normalize_home_runs(make_demo_home_runs(n=15, seed=8))
    summary = career_summary(cleaned)
    assert summary["home_runs"] == 15
    assert summary["longest"] == cleaned["home_run_distance"].max()
    assert summary["hardest"] == cleaned["launch_speed"].max()
