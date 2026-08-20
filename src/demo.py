from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


PITCHES = [
    ("FF", "4-Seam Fastball", 95.2),
    ("SI", "Sinker", 94.0),
    ("SL", "Slider", 86.1),
    ("CH", "Changeup", 87.6),
    ("CU", "Curveball", 80.5),
    ("FC", "Cutter", 91.3),
]
TEAMS = ["LAD", "SD", "SF", "ARI", "COL", "ATL", "NYM", "CHC", "STL", "PHI"]


def make_demo_home_runs(n: int = 92, seed: int = 42) -> pd.DataFrame:
    """Generate clearly labeled synthetic home-run rows for offline testing."""
    rng = np.random.default_rng(seed)
    start = date(2018, 4, 3)
    dates = sorted(start + timedelta(days=int(value)) for value in rng.integers(0, 8 * 365, n))
    rows: list[dict[str, object]] = []

    for index, game_date in enumerate(dates, start=1):
        away, home = rng.choice(TEAMS, size=2, replace=False)
        top = bool(rng.integers(0, 2))
        pitch_type, pitch_name, base_speed = PITCHES[int(rng.integers(0, len(PITCHES)))]
        launch_speed = float(np.clip(rng.normal(105.5, 5.8), 89, 121))
        launch_angle = float(np.clip(rng.normal(27.0, 7.0), 10, 48))
        distance = float(np.clip(260 + 1.25 * launch_speed + 1.7 * launch_angle + rng.normal(0, 24), 330, 485))
        balls = int(rng.integers(0, 4))
        strikes = int(rng.integers(0, 3))
        inning = int(rng.integers(1, 10))
        batter_team = away if top else home
        opponent = home if top else away
        rows.append(
            {
                "pitch_type": pitch_type,
                "game_date": game_date.isoformat(),
                "release_speed": base_speed + rng.normal(0, 1.6),
                "player_name": "Slugger, Demo",
                "batter": 999001,
                "pitcher": 800000 + index,
                "events": "home_run",
                "description": "hit_into_play",
                "des": f"Demo Slugger homers against {opponent}. (Synthetic demonstration row.)",
                "game_type": "R",
                "stand": "L",
                "p_throws": rng.choice(["L", "R"]),
                "home_team": home,
                "away_team": away,
                "balls": balls,
                "strikes": strikes,
                "game_year": game_date.year,
                "on_1b": 700001 if rng.random() < 0.28 else np.nan,
                "on_2b": 700002 if rng.random() < 0.16 else np.nan,
                "on_3b": 700003 if rng.random() < 0.08 else np.nan,
                "outs_when_up": int(rng.integers(0, 3)),
                "inning": inning,
                "inning_topbot": "Top" if top else "Bot",
                "hit_distance_sc": round(distance),
                "launch_speed": round(launch_speed, 1),
                "launch_angle": round(launch_angle),
                "game_pk": 700000 + index,
                "sv_id": f"demo-play-{index:04d}",
                "estimated_ba_using_speedangle": round(float(np.clip(0.62 + (launch_speed - 100) / 45, 0.25, 0.99)), 3),
                "estimated_woba_using_speedangle": round(float(np.clip(1.35 + (launch_speed - 100) / 55, 0.8, 2.0)), 3),
                "estimated_slg_using_speedangle": round(float(np.clip(2.6 + (launch_speed - 100) / 20, 1.4, 4.0)), 3),
                "at_bat_number": index,
                "pitch_number": int(rng.integers(1, 9)),
                "pitch_name": pitch_name,
                "bat_score": int(rng.integers(0, 8)),
                "fld_score": int(rng.integers(0, 8)),
                "bat_speed": round(float(np.clip(rng.normal(76.0, 3.5), 67, 86)), 1),
                "swing_length": round(float(np.clip(rng.normal(7.3, 0.5), 6.0, 8.8)), 2),
                "demo_batting_team": batter_team,
            }
        )
    return pd.DataFrame(rows)
