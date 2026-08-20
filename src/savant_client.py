from __future__ import annotations

import hashlib
import io
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_CACHE_DIR, SAVANT_CSV_URL


class SavantDataError(RuntimeError):
    """Raised when Baseball Savant data cannot be downloaded or parsed."""


def build_game_type_filter(game_type_codes: Iterable[str]) -> str:
    codes = [str(code).strip() for code in game_type_codes if str(code).strip()]
    if not codes:
        raise ValueError("At least one game type is required.")
    return "|".join(codes) + "|"


def build_savant_params(
    player_id: int,
    start_date: date,
    end_date: date,
    game_type_codes: Iterable[str],
) -> dict[str, str]:
    """Build parameters that mirror a Baseball Savant Statcast Search query."""
    game_filter = build_game_type_filter(game_type_codes)
    return {
        "all": "true",
        "type": "details",
        "player_type": "batter",
        "batters_lookup[]": str(int(player_id)),
        # This is the current value emitted by Savant when PA Result = Home Run.
        "hfAB": r"home\.\.run|",
        "hfPR": "",
        "hfGT": game_filter,
        "hfSea": f"{start_date.year}|" if start_date.year == end_date.year else "",
        "game_date_gt": start_date.isoformat(),
        "game_date_lt": end_date.isoformat(),
        "group_by": "name-event",
        "sort_col": "pitches",
        "sort_order": "desc",
        "player_event_sort": "api_h_launch_speed",
        "min_pitches": "0",
        "min_results": "0",
        "min_pas": "0",
        "chk_event_hit_distance_sc": "on",
        "chk_event_launch_speed": "on",
        "chk_event_launch_angle": "on",
        "hfPT": "",
        "hfBBT": "",
        "hfBBL": "",
        "hfC": "",
        "hfFlag": "",
        "hfInfield": "",
        "hfInn": "",
        "hfMo": "",
        "hfNewZones": "",
        "hfOpponent": "",
        "hfOutfield": "",
        "hfOuts": "",
        "hfPull": "",
        "hfRO": "",
        "hfSA": "",
        "hfSit": "",
        "hfStadium": "",
        "hfTeam": "",
        "hfZ": "",
        "home_road": "",
        "metric_1": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "position": "",
    }


def build_savant_url(params: dict[str, str]) -> str:
    return f"{SAVANT_CSV_URL}?{urlencode(params, doseq=True)}"


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "StatcastHomeRunCurve/1.0 (educational project)",
            "Accept": "text/csv,application/csv,text/plain,*/*",
            "Referer": "https://baseballsavant.mlb.com/statcast_search",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _cache_path(
    cache_dir: Path,
    player_id: int,
    year: int,
    game_type_codes: Iterable[str],
) -> Path:
    game_types = "-".join(sorted(str(code) for code in game_type_codes))
    digest = hashlib.sha1(game_types.encode("utf-8")).hexdigest()[:8]
    return cache_dir / f"player_{int(player_id)}_{int(year)}_{digest}.csv"


def _cache_is_fresh(path: Path, year: int, current_year: int) -> bool:
    if not path.exists():
        return False
    if year < current_year:
        return True
    age_seconds = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age_seconds < 6 * 60 * 60


def fetch_savant_season(
    player_id: int,
    year: int,
    game_type_codes: Iterable[str],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
    timeout: int = 90,
    today: date | None = None,
) -> pd.DataFrame:
    """Download one player's home-run rows for a season."""
    today = today or date.today()
    game_codes = tuple(game_type_codes)

    # Serverless hosts such as Vercel expose the deployed application directory
    # as read-only. Use the configured temporary directory when possible, but
    # continue without disk caching if the filesystem cannot be written.
    cache_available = True
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_available = False

    path = _cache_path(cache_dir, player_id, year, game_codes)

    if cache_available and not force_refresh and _cache_is_fresh(path, year, today.year):
        try:
            return _read_cached_or_empty(path)
        except (OSError, pd.errors.ParserError):
            path.unlink(missing_ok=True)

    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today) if year == today.year else date(year, 12, 31)
    if start > today:
        return pd.DataFrame()

    params = build_savant_params(player_id, start, end, game_codes)
    session = _session()
    try:
        response = session.get(
            SAVANT_CSV_URL,
            params=params,
            timeout=(10, timeout),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SavantDataError(
            f"Baseball Savant could not return {year} data: {exc}"
        ) from exc

    text = response.text.lstrip("\ufeff").strip()
    if not text:
        frame = pd.DataFrame()
    elif text.startswith("<"):
        raise SavantDataError(
            "Baseball Savant returned a webpage instead of CSV data. "
            "The query may have been rate-limited or Savant may have changed its search endpoint."
        )
    else:
        try:
            frame = pd.read_csv(io.StringIO(text), low_memory=False)
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise SavantDataError(f"Could not parse Savant's {year} CSV response.") from exc

    # Cache when the host provides a writable filesystem. Serverless /tmp
    # storage is ephemeral, so this is only a performance optimization.
    if frame.empty and len(frame.columns) == 0:
        if cache_available:
            try:
                path.write_text("__empty__\n", encoding="utf-8")
            except OSError:
                pass
        return pd.DataFrame()
    if cache_available:
        try:
            frame.to_csv(path, index=False)
        except OSError:
            pass
    return frame


def _read_cached_or_empty(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if list(frame.columns) == ["__empty__"]:
        return pd.DataFrame()
    return frame


def fetch_career_home_runs(
    player_id: int,
    start_year: int,
    end_year: int,
    game_type_codes: Iterable[str],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
    polite_delay_seconds: float = 0.25,
    today: date | None = None,
) -> pd.DataFrame:
    """Fetch seasonal Savant rows and combine them into one career dataframe."""
    if end_year < start_year:
        raise ValueError("end_year must be greater than or equal to start_year")

    today = today or date.today()
    game_codes = tuple(game_type_codes)
    years = list(range(int(start_year), int(end_year) + 1))
    frames: list[pd.DataFrame] = []

    for index, year in enumerate(years, start=1):
        if progress:
            progress(index, len(years), year)
        path = _cache_path(cache_dir, player_id, year, game_codes)
        was_cached = (not force_refresh) and _cache_is_fresh(path, year, today.year)
        if was_cached:
            frame = _read_cached_or_empty(path)
        else:
            frame = fetch_savant_season(
                player_id,
                year,
                game_codes,
                cache_dir=cache_dir,
                force_refresh=force_refresh,
                today=today,
            )
            if polite_delay_seconds > 0 and index < len(years):
                time.sleep(polite_delay_seconds)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)
