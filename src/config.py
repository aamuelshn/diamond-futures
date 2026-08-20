from __future__ import annotations

import os
import tempfile
from pathlib import Path

APP_TITLE = "Diamond Futures"
APP_SUBTITLE = "Explore thousands of plausible futures for any active MLB player."

MLB_PEOPLE_SEARCH_URL = "https://statsapi.mlb.com/api/v1/people/search"
MLB_PERSON_URL = "https://statsapi.mlb.com/api/v1/people/{player_id}"
MLB_PLAYER_STATS_URL = "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
SAVANT_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
SAVANT_CUSTOM_URL = "https://baseballsavant.mlb.com/leaderboard/custom"
FANGRAPHS_LEADERS_URL = "https://www.fangraphs.com/api/leaders/major-league/data"
SAVANT_PLAYER_URL = "https://baseballsavant.mlb.com/savant-player/{slug}-{player_id}"
SAVANT_GAME_URL = "https://baseballsavant.mlb.com/gamefeed?gamePk={game_pk}"
SAVANT_VIDEO_URL = "https://baseballsavant.mlb.com/sporty-videos?playId={play_id}"

STATCAST_METRICS_START_YEAR = 2015
SAVANT_EARLIEST_YEAR = 2008

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "HOME_RUN_CURVE_CACHE_DIR",
        str(Path(tempfile.gettempdir()) / "statcast_home_run_curve" / "savant"),
    )
)
DEMO_DATA_PATH = PROJECT_ROOT / "data" / "demo_home_runs.csv"
AGING_PRIORS_PATH = PROJECT_ROOT / "data" / "aging_priors.json"
HISTORICAL_COMPS_PATH = PROJECT_ROOT / "data" / "historical_comps.json.gz"
PLAYER_ID_MAP_PATH = PROJECT_ROOT / "data" / "player_id_map.csv.gz"

GAME_TYPE_OPTIONS = {
    "Regular season": "R",
    "Postseason": "PO",
    "Spring training": "S",
}

GAME_TYPE_LABELS = {
    "R": "Regular season",
    "F": "Wild Card",
    "D": "Division Series",
    "L": "League Championship Series",
    "W": "World Series",
    "S": "Spring training",
    "E": "Exhibition",
}

PITCH_TYPE_NAMES = {
    "FF": "4-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "ST": "Sweeper",
    "CU": "Curveball",
    "KC": "Knuckle Curve",
    "CH": "Changeup",
    "FS": "Splitter",
    "SV": "Slurve",
    "KN": "Knuckleball",
}
