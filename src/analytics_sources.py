from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any, Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    FANGRAPHS_LEADERS_URL,
    MLB_PLAYER_STATS_URL,
    PLAYER_ID_MAP_PATH,
    SAVANT_CUSTOM_URL,
)


class AnalyticsSourceError(RuntimeError):
    """Raised when a required live analytics source cannot be read."""


def _session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "DiamondFutures/1.0 (educational baseball research)",
            "Accept": "application/json,text/csv,text/plain,*/*",
            "Referer": "https://baseballsavant.mlb.com/",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", ".---", "-.--"):
            return default
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_float(value, float(default))))


def _innings(value: Any) -> float:
    """Convert baseball's 51.2 notation to 51 and two thirds innings."""
    text = str(value or "0")
    if "." not in text:
        return _float(text)
    whole, outs = text.split(".", 1)
    return _float(whole) + min(2, _int(outs)) / 3


def fetch_mlb_history(player_id: int, *, timeout: int = 24) -> dict[str, list[dict[str, Any]]]:
    session = _session()
    try:
        response = session.get(
            MLB_PLAYER_STATS_URL.format(player_id=int(player_id)),
            params={
                "stats": "yearByYear",
                "group": "hitting,pitching",
                "gameType": "R",
                "hydrate": "team",
            },
            timeout=(7, timeout),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AnalyticsSourceError(
            "MLB could not return this player's season history. Please try again in a moment."
        ) from exc

    result: dict[str, list[dict[str, Any]]] = {"hitter": [], "pitcher": []}
    for block in payload.get("stats", []):
        group = str((block.get("group") or {}).get("displayName", "")).casefold()
        role = "hitter" if group == "hitting" else "pitcher" if group == "pitching" else None
        if role is None:
            continue
        by_season: dict[int, dict[str, Any]] = {}
        for split in block.get("splits", []):
            stat = split.get("stat") or {}
            season = _int(split.get("season"))
            team = split.get("team") or {}
            if not season:
                continue
            if role == "hitter":
                row = {
                    "season": season,
                    "age": _int(stat.get("age")),
                    "team": team.get("abbreviation") or team.get("name") or "MLB",
                    "games": _int(stat.get("gamesPlayed")),
                    "pa": _int(stat.get("plateAppearances")),
                    "ab": _int(stat.get("atBats")),
                    "runs": _int(stat.get("runs")),
                    "hits": _int(stat.get("hits")),
                    "doubles": _int(stat.get("doubles")),
                    "triples": _int(stat.get("triples")),
                    "hr": _int(stat.get("homeRuns")),
                    "rbi": _int(stat.get("rbi")),
                    "bb": _int(stat.get("baseOnBalls")),
                    "so": _int(stat.get("strikeOuts")),
                    "sb": _int(stat.get("stolenBases")),
                    "cs": _int(stat.get("caughtStealing")),
                    "avg": _float(stat.get("avg")),
                    "obp": _float(stat.get("obp")),
                    "slg": _float(stat.get("slg")),
                    "ops": _float(stat.get("ops")),
                }
                workload = row["pa"]
            else:
                row = {
                    "season": season,
                    "age": _int(stat.get("age")),
                    "team": team.get("abbreviation") or team.get("name") or "MLB",
                    "games": _int(stat.get("gamesPitched") or stat.get("gamesPlayed")),
                    "starts": _int(stat.get("gamesStarted")),
                    "ip": round(_innings(stat.get("inningsPitched")), 2),
                    "wins": _int(stat.get("wins")),
                    "losses": _int(stat.get("losses")),
                    "saves": _int(stat.get("saves")),
                    "so": _int(stat.get("strikeOuts")),
                    "bb": _int(stat.get("baseOnBalls")),
                    "hr": _int(stat.get("homeRuns")),
                    "er": _int(stat.get("earnedRuns")),
                    "era": _float(stat.get("era")),
                    "whip": _float(stat.get("whip")),
                    "k9": _float(stat.get("strikeoutsPer9Inn")),
                    "bb9": _float(stat.get("walksPer9Inn")),
                    "hr9": _float(stat.get("homeRunsPer9")),
                }
                workload = row["ip"]
            previous = by_season.get(season)
            previous_workload = (previous or {}).get("pa" if role == "hitter" else "ip", -1)
            if workload >= previous_workload:
                by_season[season] = row
        result[role] = sorted(by_season.values(), key=lambda item: item["season"])
    return result


HITTER_SAVANT_FIELDS = (
    "pa,k_percent,bb_percent,woba,xwoba,barrel_batted_rate,hard_hit_percent,"
    "avg_best_speed,exit_velocity_avg,launch_angle_avg,whiff_percent,swing_percent"
)
PITCHER_SAVANT_FIELDS = (
    "pa,k_percent,bb_percent,woba,xwoba,barrel_batted_rate,hard_hit_percent,"
    "exit_velocity_avg,out_zone_percent,in_zone_percent,whiff_percent,swing_percent"
)


@lru_cache(maxsize=12)
def _savant_leaderboard(year: int, role: str, timeout: int) -> pd.DataFrame:
    selections = HITTER_SAVANT_FIELDS if role == "hitter" else PITCHER_SAVANT_FIELDS
    session = _session()
    # Savant currently rejects descriptive research-tool user agents on this
    # CSV route while accepting a neutral HTTP client header.
    session.headers.update({"User-Agent": "curl/8.7.1", "Accept": "*/*"})
    session.headers.pop("Referer", None)
    try:
        response = session.get(
            SAVANT_CUSTOM_URL,
            params={
                "year": int(year),
                "type": "batter" if role == "hitter" else "pitcher",
                "filter": "",
                "sort": "xwoba",
                "sortDir": "desc",
                "min": "10",
                "selections": selections,
                "chart": "false",
                "x": "pa",
                "y": "pa",
                "r": "no",
                "csv": "true",
            },
            timeout=(6, timeout),
        )
        response.raise_for_status()
        text = response.text.lstrip("\ufeff").strip()
        if not text or text.startswith("<"):
            raise ValueError("Savant did not return CSV")
        return pd.read_csv(io.StringIO(text), low_memory=False)
    except (requests.RequestException, ValueError, pd.errors.ParserError) as exc:
        raise AnalyticsSourceError(f"Baseball Savant did not return its {year} leaderboard.") from exc


def _clean_savant_row(row: pd.Series) -> dict[str, Any]:
    aliases = {
        "pa": "pa", "bf": "bf", "k_percent": "k_percent", "bb_percent": "bb_percent",
        "woba": "woba", "xwoba": "xwoba", "barrel_batted_rate": "barrel_percent",
        "hard_hit_percent": "hard_hit_percent", "avg_best_speed": "ev50",
        "exit_velocity_avg": "exit_velocity", "launch_angle_avg": "launch_angle",
        "whiff_percent": "whiff_percent", "swing_percent": "swing_percent",
        "out_zone_percent": "out_zone_percent", "in_zone_percent": "in_zone_percent",
    }
    cleaned: dict[str, Any] = {"season": _int(row.get("year"))}
    normalized = {str(key).strip().casefold().replace(" ", "_"): value for key, value in row.items()}
    for source, output in aliases.items():
        if source in normalized:
            cleaned[output] = _float(normalized[source])
    return cleaned


def fetch_statcast_history(
    player_id: int,
    role: str,
    years: Iterable[int],
    *,
    timeout: int = 24,
) -> list[dict[str, Any]]:
    requested = sorted({int(year) for year in years if int(year) >= 2015}, reverse=True)[:3]
    if not requested:
        return []
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(3, len(requested))) as executor:
        futures = {executor.submit(_savant_leaderboard, year, role, timeout): year for year in requested}
        for future in as_completed(futures):
            try:
                frame = future.result()
            except AnalyticsSourceError:
                continue
            id_column = next((column for column in frame.columns if str(column).strip().casefold() == "player_id"), None)
            if id_column is None:
                continue
            player_ids = pd.to_numeric(frame[id_column], errors="coerce")
            match = frame.loc[player_ids.eq(int(player_id))]
            if not match.empty:
                rows.append(_clean_savant_row(match.iloc[0]))
    return sorted(rows, key=lambda item: item.get("season", 0))


@lru_cache(maxsize=1)
def _fangraphs_id_map() -> dict[int, int]:
    try:
        frame = pd.read_csv(PLAYER_ID_MAP_PATH, compression="gzip")
    except (OSError, pd.errors.ParserError):
        return {}
    return {
        int(row.key_mlbam): int(row.key_fangraphs)
        for row in frame.itertuples(index=False)
        if pd.notna(row.key_mlbam) and pd.notna(row.key_fangraphs)
    }


def fetch_fangraphs_benchmark(
    player_id: int,
    role: str,
    season: int,
    *,
    timeout: int = 5,
) -> dict[str, Any] | None:
    """Fetch an optional FanGraphs benchmark without bypassing access controls."""
    fangraphs_id = _fangraphs_id_map().get(int(player_id))
    if not fangraphs_id:
        return None
    session = _session()
    session.headers.update({"Referer": "https://www.fangraphs.com/leaders/major-league"})
    try:
        response = session.get(
            FANGRAPHS_LEADERS_URL,
            params={
                "age": "", "pos": "all", "stats": "bat" if role == "hitter" else "pit",
                "lg": "all", "qual": "0", "season": int(season), "season1": int(season),
                "month": "0", "team": "0", "pageitems": "5", "pagenum": "1", "ind": "0",
                "rost": "0", "players": str(fangraphs_id), "type": "8", "sortdir": "default",
                "sortstat": "WAR",
            },
            timeout=(3, timeout),
        )
        response.raise_for_status()
        if response.text.lstrip().startswith("<"):
            return None
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    data = payload.get("data", payload if isinstance(payload, list) else [])
    if not isinstance(data, list) or not data:
        return None
    row = data[0]
    keys = ["WAR", "wRC+", "wOBA", "K%", "BB%"] if role == "hitter" else ["WAR", "ERA", "FIP", "xFIP", "K-BB%"]
    return {"season": int(season), **{key: row.get(key) for key in keys if row.get(key) is not None}}
