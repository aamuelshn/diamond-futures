from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from .config import (
    GAME_TYPE_LABELS,
    PITCH_TYPE_NAMES,
    SAVANT_GAME_URL,
    SAVANT_VIDEO_URL,
)


class HomeRunDataError(ValueError):
    """Raised when a dataframe cannot be interpreted as Savant home-run data."""


NUMERIC_COLUMNS = [
    "hit_distance_sc",
    "hit_distance",
    "launch_speed",
    "launch_angle",
    "release_speed",
    "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle",
    "estimated_slg_using_speedangle",
    "bat_speed",
    "swing_length",
    "balls",
    "strikes",
    "inning",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "bat_score",
    "fld_score",
    "home_score",
    "away_score",
    "delta_home_win_exp",
    "delta_run_exp",
]


def slugify_player_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or "player"


def _first_existing(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _safe_text(series: pd.Series, fallback: str = "") -> pd.Series:
    return series.fillna(fallback).astype(str).replace({"nan": fallback, "<NA>": fallback})


def _format_base_state(row: pd.Series) -> str:
    occupied: list[str] = []
    if pd.notna(row.get("on_1b")):
        occupied.append("1B")
    if pd.notna(row.get("on_2b")):
        occupied.append("2B")
    if pd.notna(row.get("on_3b")):
        occupied.append("3B")
    return ", ".join(occupied) if occupied else "Bases empty"


def normalize_home_runs(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean Savant rows and add fields used by charts and hover labels."""
    if raw is None or raw.empty:
        return pd.DataFrame()

    frame = raw.copy()
    frame.columns = [str(column).strip().lstrip("\ufeff") for column in frame.columns]

    # Empty-season cache marker.
    if list(frame.columns) == ["__empty__"]:
        return pd.DataFrame()

    if "events" in frame.columns:
        events = _safe_text(frame["events"]).str.casefold()
        frame = frame.loc[events.eq("home_run")].copy()
    elif "des" in frame.columns:
        descriptions = _safe_text(frame["des"]).str.casefold()
        possible = descriptions.str.contains(r"\bhomers?\b|\bhome run\b", regex=True)
        if possible.any():
            frame = frame.loc[possible].copy()
        else:
            raise HomeRunDataError(
                "The CSV has no 'events' column and no rows that can be identified as home runs."
            )
    else:
        raise HomeRunDataError(
            "The CSV is missing both 'events' and 'des'; it cannot be verified as home-run data."
        )

    if frame.empty:
        return frame
    if "game_date" not in frame.columns:
        raise HomeRunDataError("The CSV is missing the required 'game_date' column.")

    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce")
    frame = frame.loc[frame["game_date"].notna()].copy()

    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    distance_source = _first_existing(frame, ["hit_distance_sc", "hit_distance"])
    if distance_source:
        frame["home_run_distance"] = pd.to_numeric(frame[distance_source], errors="coerce")
    else:
        frame["home_run_distance"] = np.nan

    defaults: dict[str, object] = {
        "game_type": "R",
        "home_team": "",
        "away_team": "",
        "inning_topbot": "",
        "inning": np.nan,
        "balls": np.nan,
        "strikes": np.nan,
        "pitch_type": "",
        "pitch_name": "",
        "release_speed": np.nan,
        "launch_speed": np.nan,
        "launch_angle": np.nan,
        "estimated_ba_using_speedangle": np.nan,
        "estimated_woba_using_speedangle": np.nan,
        "estimated_slg_using_speedangle": np.nan,
        "bat_speed": np.nan,
        "swing_length": np.nan,
        "des": "",
        "sv_id": "",
        "play_id": "",
        "game_pk": np.nan,
        "at_bat_number": np.nan,
        "pitch_number": np.nan,
        "on_1b": np.nan,
        "on_2b": np.nan,
        "on_3b": np.nan,
        "outs_when_up": np.nan,
        "bat_score": np.nan,
        "fld_score": np.nan,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default

    dedupe_keys = [
        key
        for key in ["game_pk", "at_bat_number", "pitch_number"]
        if key in frame.columns and frame[key].notna().any()
    ]
    if dedupe_keys:
        frame = frame.drop_duplicates(subset=dedupe_keys, keep="last")
    else:
        frame = frame.drop_duplicates()

    sort_keys = [
        key
        for key in ["game_date", "game_pk", "at_bat_number", "pitch_number"]
        if key in frame.columns
    ]
    frame = frame.sort_values(sort_keys, kind="stable").reset_index(drop=True)

    if "game_year" in frame.columns:
        frame["season"] = pd.to_numeric(frame["game_year"], errors="coerce")
        frame["season"] = frame["season"].fillna(frame["game_date"].dt.year)
    else:
        frame["season"] = frame["game_date"].dt.year
    frame["season"] = frame["season"].astype(int)

    frame["home_run_number"] = np.arange(1, len(frame) + 1)
    frame["season_home_run_number"] = frame.groupby("season").cumcount() + 1
    frame["game_date_label"] = frame["game_date"].dt.strftime("%b %d, %Y")
    frame["game_date_label"] = frame["game_date_label"].str.replace(r"\b0(\d)\b", r"\1", regex=True)

    top = _safe_text(frame["inning_topbot"]).str.casefold().str.startswith("top")
    frame["batting_team"] = np.where(top, _safe_text(frame["away_team"]), _safe_text(frame["home_team"]))
    frame["opponent"] = np.where(top, _safe_text(frame["home_team"]), _safe_text(frame["away_team"]))
    frame["matchup"] = _safe_text(frame["away_team"]) + " @ " + _safe_text(frame["home_team"])
    frame["inning_label"] = (
        _safe_text(frame["inning_topbot"]).str.title()
        + " "
        + pd.to_numeric(frame["inning"], errors="coerce").fillna(0).astype(int).astype(str)
    ).str.strip()

    balls = pd.to_numeric(frame["balls"], errors="coerce")
    strikes = pd.to_numeric(frame["strikes"], errors="coerce")
    frame["count_label"] = balls.fillna(0).astype(int).astype(str) + "-" + strikes.fillna(0).astype(int).astype(str)

    frame["base_state"] = frame.apply(_format_base_state, axis=1)
    frame["game_type_label"] = _safe_text(frame["game_type"]).map(GAME_TYPE_LABELS).fillna(_safe_text(frame["game_type"]))

    pitch_name = _safe_text(frame["pitch_name"])
    pitch_type = _safe_text(frame["pitch_type"])
    frame["pitch_label"] = np.where(
        pitch_name.str.len() > 0,
        pitch_name,
        pitch_type.map(PITCH_TYPE_NAMES).fillna(pitch_type),
    )

    frame["score_label"] = (
        pd.to_numeric(frame["bat_score"], errors="coerce").fillna(0).astype(int).astype(str)
        + "-"
        + pd.to_numeric(frame["fld_score"], errors="coerce").fillna(0).astype(int).astype(str)
    )

    frame["game_url"] = frame["game_pk"].apply(
        lambda value: SAVANT_GAME_URL.format(game_pk=int(value)) if pd.notna(value) else ""
    )
    play_ids = _safe_text(frame["play_id"])
    fallback_play_ids = _safe_text(frame["sv_id"])
    play_ids = play_ids.where(play_ids.str.len() > 0, fallback_play_ids)
    frame["video_url"] = play_ids.apply(
        lambda value: (
            SAVANT_VIDEO_URL.format(play_id=value)
            if value and value.lower() != "nan" and len(value) >= 12
            else ""
        )
    )

    # Rolling values are by home-run sequence, not by calendar day.
    for source, output in [
        ("home_run_distance", "rolling_distance_10"),
        ("launch_speed", "rolling_exit_velocity_10"),
        ("launch_angle", "rolling_launch_angle_10"),
    ]:
        frame[output] = pd.to_numeric(frame[source], errors="coerce").rolling(10, min_periods=3).mean()

    return frame.reset_index(drop=True)


def filter_home_runs(
    frame: pd.DataFrame,
    seasons: Iterable[int] | None = None,
    teams: Iterable[str] | None = None,
) -> pd.DataFrame:
    result = frame.copy()
    if seasons is not None:
        result = result[result["season"].isin([int(value) for value in seasons])]
    if teams is not None:
        result = result[result["batting_team"].isin([str(value) for value in teams])]
    return result.reset_index(drop=True)


def career_summary(frame: pd.DataFrame) -> dict[str, float | int | str | None]:
    if frame.empty:
        return {
            "home_runs": 0,
            "longest": None,
            "hardest": None,
            "average_distance": None,
            "average_exit_velocity": None,
            "first_date": None,
            "latest_date": None,
        }

    return {
        "home_runs": int(len(frame)),
        "longest": float(frame["home_run_distance"].max()) if frame["home_run_distance"].notna().any() else None,
        "hardest": float(frame["launch_speed"].max()) if frame["launch_speed"].notna().any() else None,
        "average_distance": float(frame["home_run_distance"].mean()) if frame["home_run_distance"].notna().any() else None,
        "average_exit_velocity": float(frame["launch_speed"].mean()) if frame["launch_speed"].notna().any() else None,
        "first_date": frame["game_date"].min().date().isoformat(),
        "latest_date": frame["game_date"].max().date().isoformat(),
    }
