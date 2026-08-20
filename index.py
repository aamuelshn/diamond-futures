from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from src.config import DEMO_DATA_PATH, STATCAST_METRICS_START_YEAR
from src.analytics_sources import (
    AnalyticsSourceError,
    fetch_fangraphs_benchmark,
    fetch_mlb_history,
    fetch_statcast_history,
)
from src.career_model import (
    MODEL_VERSION,
    available_roles,
    choose_role,
    demo_inputs,
    simulate_career,
)
from src.data import HomeRunDataError, career_summary, normalize_home_runs
from src.mlb_client import PlayerLookupError, get_player_detail, search_players
from src.savant_client import SavantDataError, fetch_career_home_runs

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"

app = FastAPI(title="Diamond Futures", description="The CURVE Engine MLB career simulator")


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _serialize(frame: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "game_date", "game_date_label", "season", "home_run_number",
        "season_home_run_number", "home_run_distance", "launch_speed",
        "launch_angle", "bat_speed", "swing_length", "release_speed",
        "pitch_label", "pitch_type", "matchup", "inning_label", "count_label",
        "base_state", "score_label", "batting_team", "opponent", "game_type_label",
        "estimated_ba_using_speedangle", "estimated_woba_using_speedangle",
        "estimated_slg_using_speedangle", "delta_home_win_exp", "delta_run_exp",
        "des", "game_url", "video_url", "rolling_distance_10",
        "rolling_exit_velocity_10", "rolling_launch_angle_10",
    ]
    present = [c for c in columns if c in frame.columns]
    records: list[dict[str, Any]] = []
    for row in frame[present].to_dict(orient="records"):
        records.append({key: _clean_value(value) for key, value in row.items()})
    return records


def _payload(frame: pd.DataFrame, player: dict[str, Any] | None = None, source: str = "") -> dict[str, Any]:
    normalized = normalize_home_runs(frame)
    return {
        "player": player,
        "source": source,
        "summary": career_summary(normalized),
        "home_runs": _serialize(normalized),
    }


@app.get("/", response_class=HTMLResponse)
def root() -> FileResponse:
    return FileResponse(PUBLIC / "index.html", media_type="text/html")


@app.get("/{filename}", include_in_schema=False)
def static_asset(filename: str) -> FileResponse:
    if filename not in {"app.js", "styles.css", "og.png"}:
        raise HTTPException(status_code=404)
    media = "application/javascript" if filename.endswith(".js") else "image/png" if filename.endswith(".png") else "text/css"
    return FileResponse(PUBLIC / filename, media_type=media)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/search")
def player_search(q: str = Query(min_length=2, max_length=80)) -> dict[str, Any]:
    try:
        matches = search_players(q)
    except PlayerLookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    active_matches = [candidate for candidate in matches if candidate.active is True]
    visible = active_matches or matches
    return {"matches": [candidate.to_dict() | {"label": candidate.label} for candidate in visible[:10]]}


def _source_ledger(
    history: dict[str, list[dict[str, Any]]],
    statcast: list[dict[str, Any]],
    fangraphs: dict[str, Any] | None,
    *,
    demo_mode: bool = False,
) -> list[dict[str, Any]]:
    seasons = sorted({row["season"] for rows in history.values() for row in rows})
    return [
        {
            "name": "MLB Stats API", "status": "demo" if demo_mode else "connected",
            "detail": "Synthetic season history" if demo_mode else f"Official season history · {seasons[0]}–{seasons[-1]}" if seasons else "No season history",
        },
        {
            "name": "Baseball Savant", "status": "demo" if demo_mode else "connected" if statcast else "limited",
            "detail": "Synthetic Statcast profile" if demo_mode else f"{len(statcast)} Statcast season profiles" if statcast else "Live Statcast unavailable; uncertainty widened",
        },
        {
            "name": "FanGraphs", "status": "connected" if fangraphs else "reference",
            "detail": "Latest-season benchmark loaded" if fangraphs else "Optional benchmark only; protected access was respected",
        },
        {
            "name": "SABR Lahman", "status": "trained",
            "detail": "Aging transitions and historical twins · 1980–2025",
        },
        {
            "name": "Chadwick Register", "status": "matched",
            "detail": "Cross-source player identity matching",
        },
    ]


def _live_simulation(
    player_id: int,
    requested_role: str,
    adjustments: dict[str, float],
    simulations: int,
) -> dict[str, Any]:
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            player_future = executor.submit(get_player_detail, player_id)
            history_future = executor.submit(fetch_mlb_history, player_id)
            player = player_future.result().to_dict()
            history = history_future.result()
    except (PlayerLookupError, AnalyticsSourceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    roles = available_roles(history)
    role = choose_role(history, requested_role)
    role_history = history.get(role) or []
    if not role_history:
        raise HTTPException(status_code=422, detail="This player does not have enough MLB history to simulate yet.")
    years = [int(row["season"]) for row in role_history[-3:]]
    latest_season = max(years)
    with ThreadPoolExecutor(max_workers=2) as executor:
        savant_future = executor.submit(fetch_statcast_history, player_id, role, years)
        fangraphs_future = executor.submit(fetch_fangraphs_benchmark, player_id, role, latest_season)
        try:
            statcast = savant_future.result()
        except AnalyticsSourceError:
            statcast = []
        try:
            fangraphs = fangraphs_future.result()
        except AnalyticsSourceError:
            fangraphs = None
    try:
        result = simulate_career(
            player, history, statcast, requested_role=role, adjustments=adjustments, simulations=simulations
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["sources"] = _source_ledger(history, statcast, fangraphs)
    result["fangraphs"] = fangraphs
    return result


@app.get("/api/simulate")
def career_simulation(
    player_id: int = Query(gt=0),
    role: str = Query(default="auto", pattern="^(auto|hitter|pitcher)$"),
    skill: float = Query(default=0, ge=-12, le=12),
    availability: float = Query(default=0, ge=-25, le=25),
    longevity: float = Query(default=0, ge=-20, le=20),
    environment: float = Query(default=0, ge=-12, le=12),
    simulations: int = Query(default=5000, ge=1000, le=10000),
) -> dict[str, Any]:
    adjustments = {"skill": skill, "availability": availability, "longevity": longevity, "environment": environment}
    return _live_simulation(player_id, role, adjustments, simulations)


@app.post("/api/resimulate")
def resimulate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    player = payload.get("player") or {}
    history = payload.get("history") or {}
    statcast = payload.get("statcast") or []
    if not player.get("player_id") or not isinstance(history, dict):
        raise HTTPException(status_code=400, detail="The saved player profile is incomplete. Load the player again.")
    safe_history = {
        "hitter": list(history.get("hitter") or [])[-40:],
        "pitcher": list(history.get("pitcher") or [])[-40:],
    }
    try:
        result = simulate_career(
            player,
            safe_history,
            list(statcast)[-3:],
            requested_role=str(payload.get("role") or "auto"),
            adjustments=dict(payload.get("adjustments") or {}),
            simulations=int(payload.get("simulations") or 5000),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["sources"] = payload.get("sources") or _source_ledger(safe_history, statcast, None)
    result["fangraphs"] = payload.get("fangraphs")
    return result


@app.get("/api/demo-simulation")
def demo_simulation(
    skill: float = Query(default=0, ge=-12, le=12),
    availability: float = Query(default=0, ge=-25, le=25),
    longevity: float = Query(default=0, ge=-20, le=20),
    environment: float = Query(default=0, ge=-12, le=12),
    simulations: int = Query(default=5000, ge=1000, le=10000),
) -> dict[str, Any]:
    player, history, statcast = demo_inputs()
    adjustments = {"skill": skill, "availability": availability, "longevity": longevity, "environment": environment}
    result = simulate_career(player, history, statcast, adjustments=adjustments, simulations=simulations)
    result["sources"] = _source_ledger(history, statcast, None, demo_mode=True)
    result["fangraphs"] = None
    return result


@app.get("/api/model-info")
def model_info() -> dict[str, Any]:
    player, history, statcast = demo_inputs()
    demo_result = simulate_career(player, history, statcast, simulations=1000)
    return {
        "name": "CURVE Engine", "version": MODEL_VERSION, "default_simulations": 5000,
        "plain_english": "The model estimates current talent, applies age-specific changes learned from historical careers, separately models playing time and career survival, then runs thousands of correlated futures.",
        "backtest": demo_result["model"]["backtest"],
    }


@app.get("/api/home-runs")
def home_runs(
    player_id: int = Query(gt=0),
    player_name: str = Query(default="MLB player", max_length=100),
    start_year: int = Query(default=STATCAST_METRICS_START_YEAR, ge=2008, le=2100),
    end_year: int = Query(default_factory=lambda: date.today().year, ge=2008, le=2100),
    game_types: str = Query(default="R", max_length=20),
    force_refresh: bool = False,
) -> dict[str, Any]:
    if end_year < start_year:
        raise HTTPException(status_code=400, detail="End year must be at least the start year.")
    codes = tuple(code.strip() for code in game_types.split(",") if code.strip())
    if not codes:
        raise HTTPException(status_code=400, detail="At least one game type is required.")
    try:
        raw = fetch_career_home_runs(
            player_id,
            start_year,
            end_year,
            codes,
            force_refresh=force_refresh,
            polite_delay_seconds=0.05,
        )
        normalized = normalize_home_runs(raw)
    except (SavantDataError, HomeRunDataError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    player = {"player_id": player_id, "full_name": player_name}
    return {
        "player": player,
        "source": "Baseball Savant",
        "summary": career_summary(normalized),
        "home_runs": _serialize(normalized),
    }


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file.")
    try:
        raw_bytes = await file.read()
        raw = pd.read_csv(StringIO(raw_bytes.decode("utf-8-sig")), low_memory=False)
        return _payload(raw, source=f"Uploaded CSV: {file.filename}")
    except (UnicodeDecodeError, pd.errors.ParserError, HomeRunDataError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read this Savant CSV: {exc}") from exc


@app.get("/api/demo")
def demo() -> dict[str, Any]:
    raw = pd.read_csv(DEMO_DATA_PATH, low_memory=False)
    return _payload(raw, player={"full_name": "Synthetic Demo"}, source="Synthetic demo")
