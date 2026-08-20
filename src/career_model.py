from __future__ import annotations

import gzip
import hashlib
import json
import math
from datetime import date
from functools import lru_cache
from typing import Any

import numpy as np

from .config import AGING_PRIORS_PATH, HISTORICAL_COMPS_PATH


MODEL_VERSION = "CURVE 2026.1"
SIMULATION_YEAR = date.today().year
LEAGUE_OPS = 0.720
LEAGUE_WOBA = 0.315
LEAGUE_ERA = 4.20


@lru_cache(maxsize=1)
def _priors() -> dict[str, Any]:
    return json.loads(AGING_PRIORS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _comps() -> dict[str, list[dict[str, Any]]]:
    with gzip.open(HISTORICAL_COMPS_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return default if value in (None, "", ".---") else float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return float(max(low, min(high, value)))


def _grade(value: float) -> int:
    return int(round(_clamp(value, 20, 80)))


def _percentiles(values: np.ndarray, decimals: int = 1) -> dict[str, float]:
    p10, p50, p90 = np.percentile(values, [10, 50, 90])
    return {"p10": round(float(p10), decimals), "p50": round(float(p50), decimals), "p90": round(float(p90), decimals)}


def _weighted(rows: list[dict[str, Any]], key: str, workload_key: str) -> float:
    usable = [row for row in rows[-3:] if _float(row.get(workload_key)) > 0 and row.get(key) is not None]
    if not usable:
        return 0.0
    recency = [0.20, 0.30, 0.50][-len(usable):]
    weights = np.array(recency, dtype=float)
    samples = np.array([max(1.0, _float(row.get(workload_key))) for row in usable])
    weights *= np.sqrt(samples / samples.max())
    values = np.array([_float(row.get(key)) for row in usable])
    return float(np.average(values, weights=weights))


def _full_season_workload(row: dict[str, Any], role: str) -> float:
    if role == "hitter":
        pa = _float(row.get("pa"))
        games = max(1, int(_float(row.get("games"))))
        if int(row.get("season", 0)) == SIMULATION_YEAR and games < 145:
            return min(720.0, pa / games * 150)
        return pa
    innings = _float(row.get("ip"))
    games = max(1, int(_float(row.get("games"))))
    starts = int(_float(row.get("starts")))
    if int(row.get("season", 0)) == SIMULATION_YEAR and games < 55:
        target_games = 28 if starts / games >= 0.45 else 62
        return min(220.0, innings / games * target_games)
    return innings


def choose_role(history: dict[str, list[dict[str, Any]]], requested: str = "auto") -> str:
    if requested in {"hitter", "pitcher"} and history.get(requested):
        return requested
    hitter = sum(_float(row.get("pa")) for row in history.get("hitter", [])[-2:])
    pitcher = sum(_float(row.get("ip")) for row in history.get("pitcher", [])[-2:])
    if pitcher >= 35 and hitter < 120:
        return "pitcher"
    return "hitter" if hitter > 0 else "pitcher"


def available_roles(history: dict[str, list[dict[str, Any]]]) -> list[str]:
    roles = []
    if any(_float(row.get("pa")) >= 1 for row in history.get("hitter", [])):
        roles.append("hitter")
    if any(_float(row.get("ip")) >= 1 for row in history.get("pitcher", [])):
        roles.append("pitcher")
    return roles or ["hitter"]


def _current_age(player: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    if rows and _float(rows[-1].get("age")):
        return int(_float(rows[-1]["age"]))
    birth = player.get("birth_date")
    if birth:
        try:
            born = date.fromisoformat(str(birth)[:10])
            today = date.today()
            return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except ValueError:
            pass
    return 27


def _hitter_value(pa: np.ndarray, woba: np.ndarray, sb: np.ndarray, cs: np.ndarray, position: str) -> np.ndarray:
    batting_runs = (woba - LEAGUE_WOBA) / 1.25 * pa
    replacement = 20 * pa / 600
    position_runs = {
        "C": 11.0, "SS": 7.0, "2B": 3.0, "3B": 2.5, "CF": 2.5,
        "LF": -6.0, "RF": -6.0, "1B": -11.0, "DH": -15.0,
    }.get(str(position).upper(), 0.0) * pa / 600
    baserunning = 0.20 * sb - 0.40 * cs
    return np.maximum(-2.0, (batting_runs + replacement + position_runs + baserunning) / 10)


def _pitcher_value(ip: np.ndarray, era: np.ndarray) -> np.ndarray:
    run_prevention = (LEAGUE_ERA - era) * ip / 9
    replacement = 0.115 * ip
    return np.maximum(-1.5, (run_prevention + replacement) / 10)


def _actual_hitter_value(rows: list[dict[str, Any]], position: str) -> float:
    total = 0.0
    for row in rows:
        pa = _float(row.get("pa"))
        ops = _float(row.get("ops"), LEAGUE_OPS)
        woba = LEAGUE_WOBA + (ops - LEAGUE_OPS) * 0.28
        total += float(_hitter_value(np.array([pa]), np.array([woba]), np.array([_float(row.get("sb"))]), np.array([_float(row.get("cs"))]), position)[0])
    return total


def _actual_pitcher_value(rows: list[dict[str, Any]]) -> float:
    return sum(float(_pitcher_value(np.array([_float(row.get("ip"))]), np.array([_float(row.get("era"), LEAGUE_ERA)]))[0]) for row in rows)


def _prior(role: str, age: int) -> dict[str, float]:
    priors = _priors()[role]
    available = sorted(int(key) for key in priors)
    nearest = min(available, key=lambda value: abs(value - age))
    return priors[str(nearest)]


def _seed(player_id: int, role: str, adjustments: dict[str, float]) -> int:
    token = json.dumps([int(player_id), role, adjustments], sort_keys=True).encode("utf-8")
    return int.from_bytes(hashlib.sha256(token).digest()[:8], "big", signed=False)


def _similarity_hitter(age: int, baseline: dict[str, float]) -> list[dict[str, Any]]:
    candidates = [row for row in _comps()["hitter"] if abs(int(row["age"]) - age) <= 1]
    scales = {"ops": 0.12, "hr_rate": 0.035, "k_rate": 0.08, "bb_rate": 0.05, "sb_rate": 0.025, "pa": 180}
    weighted = {"ops": 1.5, "hr_rate": 1.1, "k_rate": 0.8, "bb_rate": 0.7, "sb_rate": 0.35, "pa": 0.5}
    scored = []
    for row in candidates:
        distance = sum(weighted[key] * ((_float(row.get(key)) - baseline[key]) / scales[key]) ** 2 for key in scales)
        scored.append((math.sqrt(distance), row))
    return _format_comps(scored, "hitter")


def _similarity_pitcher(age: int, baseline: dict[str, float]) -> list[dict[str, Any]]:
    candidates = [row for row in _comps()["pitcher"] if abs(int(row["age"]) - age) <= 1]
    scales = {"era": 1.2, "k9": 2.3, "bb9": 1.0, "hr9": 0.45, "ip": 65, "starter_share": 0.42}
    weighted = {"era": 1.2, "k9": 1.0, "bb9": 0.8, "hr9": 0.5, "ip": 0.6, "starter_share": 1.1}
    scored = []
    for row in candidates:
        distance = sum(weighted[key] * ((_float(row.get(key)) - baseline[key]) / scales[key]) ** 2 for key in scales)
        scored.append((math.sqrt(distance), row))
    return _format_comps(scored, "pitcher")


def _format_comps(scored: list[tuple[float, dict[str, Any]]], role: str) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for distance, row in sorted(scored, key=lambda item: item[0]):
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        similarity = int(round(100 * math.exp(-0.20 * distance)))
        item = {
            "name": row["name"], "age": row["age"], "season": row["year"],
            "similarity": max(45, min(98, similarity)), "next_seasons": row["next_seasons"],
        }
        if role == "hitter":
            item.update({"career_hr": row["career_hr"], "career_hits": row["career_hits"], "signature": f"{row['ops']:.3f} OPS · {round(600 * row['hr_rate'])} HR/600 PA"})
        else:
            item.update({"career_so": row["career_so"], "career_wins": row["career_wins"], "signature": f"{row['era']:.2f} ERA · {row['k9']:.1f} K/9"})
        result.append(item)
        if len(result) == 5:
            break
    return result


def _milestone(label: str, threshold: float, finals: np.ndarray, current: float, unit: str = "") -> dict[str, Any]:
    return {
        "label": label,
        "threshold": threshold,
        "current": round(float(current), 1 if unit == "CV" else 0),
        "probability": round(float(np.mean(finals >= threshold) * 100), 1),
        "unit": unit,
    }


def _hitter_simulation(
    player: dict[str, Any], rows: list[dict[str, Any]], statcast: list[dict[str, Any]],
    adjustments: dict[str, float], simulations: int,
) -> dict[str, Any]:
    latest = rows[-1]
    age = _current_age(player, rows)
    baseline_pa = np.average([_full_season_workload(row, "hitter") for row in rows[-3:]], weights=[0.2, 0.3, 0.5][-len(rows[-3:]):])
    baseline = {
        "pa": _clamp(float(baseline_pa), 80, 720),
        "ops": _clamp(_weighted(rows, "ops", "pa") or LEAGUE_OPS, 0.45, 1.20),
        "avg": _clamp(_weighted(rows, "avg", "pa") or 0.240, 0.12, 0.38),
        "hr_rate": _clamp(sum(_float(r.get("hr")) for r in rows[-3:]) / max(1, sum(_float(r.get("pa")) for r in rows[-3:])), 0.001, 0.13),
        "k_rate": _clamp(sum(_float(r.get("so")) for r in rows[-3:]) / max(1, sum(_float(r.get("pa")) for r in rows[-3:])), 0.03, 0.45),
        "bb_rate": _clamp(sum(_float(r.get("bb")) for r in rows[-3:]) / max(1, sum(_float(r.get("pa")) for r in rows[-3:])), 0.01, 0.25),
        "sb_rate": _clamp(sum(_float(r.get("sb")) for r in rows[-3:]) / max(1, sum(_float(r.get("pa")) for r in rows[-3:])), 0.0, 0.10),
        "cs_rate": _clamp(sum(_float(r.get("cs")) for r in rows[-3:]) / max(1, sum(_float(r.get("pa")) for r in rows[-3:])), 0.0, 0.04),
    }
    recent_sc = statcast[-1] if statcast else {}
    xwoba = _float(recent_sc.get("xwoba"), LEAGUE_WOBA + (baseline["ops"] - LEAGUE_OPS) * 0.28)
    observed_woba = _float(recent_sc.get("woba"), xwoba)
    blended_woba = _clamp(0.65 * xwoba + 0.35 * observed_woba, 0.22, 0.48)
    baseline["ops"] = _clamp(baseline["ops"] * 0.72 + (LEAGUE_OPS + (blended_woba - LEAGUE_WOBA) / 0.28) * 0.28, 0.48, 1.18)

    horizon = max(5, min(15, 43 - age))
    years = list(range(int(latest["season"]) + 1, int(latest["season"]) + horizon + 1))
    rng = np.random.default_rng(_seed(int(player.get("player_id", 0)), "hitter", adjustments))
    alive = np.ones(simulations, dtype=bool)
    pa = np.full(simulations, baseline["pa"])
    ops = np.full(simulations, baseline["ops"])
    avg = np.full(simulations, baseline["avg"])
    hr_rate = np.full(simulations, baseline["hr_rate"])
    k_rate = np.full(simulations, baseline["k_rate"])
    bb_rate = np.full(simulations, baseline["bb_rate"])
    sb_rate = np.full(simulations, baseline["sb_rate"])
    cumulative_hr = np.full(simulations, sum(_float(row.get("hr")) for row in rows))
    cumulative_hits = np.full(simulations, sum(_float(row.get("hits")) for row in rows))
    current_value = _actual_hitter_value(rows, str(player.get("position") or ""))
    cumulative_value = np.full(simulations, current_value)
    season_rows = []
    path_hr: list[np.ndarray] = []
    path_hits: list[np.ndarray] = []
    path_value: list[np.ndarray] = []
    path_active: list[np.ndarray] = []
    path_ops: list[np.ndarray] = []

    skill = 1 + _clamp(_float(adjustments.get("skill")), -12, 12) / 100
    availability = 1 + _clamp(_float(adjustments.get("availability")), -25, 25) / 100
    longevity = _clamp(_float(adjustments.get("longevity")), -20, 20) / 100
    environment = 1 + _clamp(_float(adjustments.get("environment")), -12, 12) / 100
    talent_bonus = _clamp((baseline["ops"] - LEAGUE_OPS) * 0.45 + (baseline["pa"] - 450) / 2200, -0.08, 0.12)

    for index, year in enumerate(years):
        transition_age = age + index
        prior = _prior("hitter", transition_age)
        survival = _clamp(_float(prior["survival"]) + talent_bonus + longevity, 0.25, 0.995)
        if index == 0 and player.get("active", True):
            survival = max(survival, 0.94)
        alive &= rng.random(simulations) < survival
        common = rng.normal(0, 1, simulations)
        ops = LEAGUE_OPS + (ops - LEAGUE_OPS) * 0.94 + _float(prior["ops_delta"]) + common * _float(prior["ops_sd"]) * 0.48
        ops = np.clip(LEAGUE_OPS + (ops - LEAGUE_OPS) * skill, 0.43, 1.18)
        hr_rate *= _float(prior["hr_factor"], 0.96) * np.exp(common * 0.10) * (1 + (skill - 1) * 1.3)
        hr_rate = np.clip(hr_rate, 0.001, 0.14)
        k_rate = np.clip(k_rate + _float(prior["k_delta"]) + rng.normal(0, 0.012, simulations), 0.04, 0.48)
        bb_rate = np.clip(bb_rate + _float(prior["bb_delta"]) + rng.normal(0, 0.008, simulations), 0.01, 0.25)
        sb_rate = np.clip(sb_rate * _float(prior["speed_factor"], 0.90) * np.exp(rng.normal(0, 0.18, simulations)), 0, 0.11)
        pa = pa * _float(prior["pa_factor"], 0.90) * np.exp(rng.normal(0, 0.18, simulations)) * availability
        pa = np.where(alive, np.clip(pa, 35, 735), 0)
        avg = np.clip(baseline["avg"] + (ops - baseline["ops"]) * 0.22 - 0.0015 * (transition_age - age), 0.12, 0.38)
        ab = pa * np.clip(0.91 - bb_rate, 0.70, 0.92)
        hits = np.rint(avg * ab)
        homers = np.rint(pa * hr_rate * environment)
        steals = np.rint(pa * sb_rate)
        caught = np.rint(pa * baseline["cs_rate"])
        woba = np.clip(blended_woba + (ops - baseline["ops"]) * 0.28, 0.20, 0.48)
        value = _hitter_value(pa, woba, steals, caught, str(player.get("position") or ""))
        cumulative_hr += homers
        cumulative_hits += hits
        cumulative_value += value
        active_season = pa >= 50
        path_hr.append(homers)
        path_hits.append(hits)
        path_value.append(value)
        path_active.append(active_season)
        path_ops.append(ops.copy())
        season_rows.append({
            "season": year, "age": transition_age + 1, "workload": _percentiles(pa, 0),
            "rate": _percentiles(ops, 3), "rate_label": "OPS", "home_runs": _percentiles(homers, 0),
            "hits": _percentiles(hits, 0), "value": _percentiles(value, 1),
            "active_probability": round(float(np.mean(active_season) * 100), 1),
        })

    active_matrix = np.vstack(path_active)
    seasons_remaining = active_matrix.sum(axis=0)
    retirement = np.full(simulations, int(latest["season"]), dtype=float)
    for idx, year in enumerate(years):
        retirement = np.where(active_matrix[idx], year, retirement)
    peak_actual = max((_float(row.get("ops")) for row in rows[-3:]), default=baseline["ops"])
    best_future_ops = np.max(np.where(active_matrix, np.vstack(path_ops), -np.inf), axis=0)
    second_peak = float(np.mean(best_future_ops >= peak_actual + 0.02) * 100)
    three_year_survival = float(np.mean(active_matrix[min(2, len(years) - 1)]) * 100)

    current_hr = sum(_float(row.get("hr")) for row in rows)
    current_hits = sum(_float(row.get("hits")) for row in rows)
    milestones = []
    for threshold in [300, 400, 500, 600, 700]:
        if threshold > current_hr and len(milestones) < 2:
            milestones.append(_milestone(f"{threshold} home runs", threshold, cumulative_hr, current_hr))
    for threshold in [1500, 2000, 2500, 3000]:
        if threshold > current_hits and len(milestones) < 4:
            milestones.append(_milestone(f"{threshold:,} hits", threshold, cumulative_hits, current_hits))
    for threshold in [30, 50, 70, 90]:
        if threshold > current_value and len(milestones) < 5:
            milestones.append(_milestone(f"{threshold} CURVE Value", threshold, cumulative_value, current_value, "CV"))

    recent_trend = 0.0
    if len(rows) >= 2:
        recent_trend = _float(rows[-1].get("ops")) - _float(rows[-2].get("ops"))
    reasons = [
        {"label": "Age curve", "impact": "positive" if age <= 27 else "negative", "detail": f"Age {age} is matched to {int(_prior('hitter', age)['sample']):,} comparable modern player-seasons."},
        {"label": "Underlying contact", "impact": "positive" if xwoba >= LEAGUE_WOBA else "negative", "detail": f"Statcast xwOBA of {xwoba:.3f} {'supports' if xwoba >= observed_woba else 'trails'} the recent results." if statcast else "Statcast was unavailable, so uncertainty is wider."},
        {"label": "Recent direction", "impact": "positive" if recent_trend >= 0 else "negative", "detail": f"Recent OPS moved {recent_trend:+.3f}; the model regresses part, not all, of that change."},
        {"label": "Role security", "impact": "positive" if baseline["pa"] >= 500 else "neutral", "detail": f"The current playing-time baseline is {baseline['pa']:.0f} PA per full season."},
    ]
    skills = [
        {"label": "Power", "grade": _grade(50 + (baseline["hr_rate"] - 0.035) * 520 + (_float(recent_sc.get("barrel_percent"), 7) - 7) * 1.1)},
        {"label": "Contact", "grade": _grade(50 + (0.22 - baseline["k_rate"]) * 130)},
        {"label": "Discipline", "grade": _grade(50 + (baseline["bb_rate"] - 0.082) * 180)},
        {"label": "Impact", "grade": _grade(50 + (xwoba - LEAGUE_WOBA) * 210)},
        {"label": "Availability", "grade": _grade(50 + (baseline["pa"] - 480) / 9)},
    ]
    confidence_score = min(94, 45 + min(28, len(rows) * 4) + (14 if statcast else 0) + (7 if baseline["pa"] >= 400 else 0))
    return {
        "baseline": {key: round(value, 3 if key != "pa" else 0) for key, value in baseline.items()},
        "seasons": season_rows,
        "summary": {
            "remaining_seasons": _percentiles(seasons_remaining, 0), "retirement_year": _percentiles(retirement, 0),
            "remaining_value": _percentiles(cumulative_value - current_value, 1), "career_value": _percentiles(cumulative_value, 1),
            "career_home_runs": _percentiles(cumulative_hr, 0), "career_hits": _percentiles(cumulative_hits, 0),
            "three_year_survival": round(three_year_survival, 1), "second_peak_probability": round(second_peak, 1),
            "cliff_risk": round(100 - three_year_survival, 1),
        },
        "milestones": milestones, "comparables": _similarity_hitter(age, baseline), "drivers": reasons,
        "skills": skills, "confidence": {"score": confidence_score, "label": "High" if confidence_score >= 80 else "Solid" if confidence_score >= 65 else "Exploratory"},
        "metric_labels": {"workload": "PA", "rate": "OPS", "count": "HR"},
    }


def _pitcher_simulation(
    player: dict[str, Any], rows: list[dict[str, Any]], statcast: list[dict[str, Any]],
    adjustments: dict[str, float], simulations: int,
) -> dict[str, Any]:
    latest = rows[-1]
    age = _current_age(player, rows)
    workloads = [_full_season_workload(row, "pitcher") for row in rows[-3:]]
    baseline_ip = np.average(workloads, weights=[0.2, 0.3, 0.5][-len(workloads):])
    totals_ip = max(1, sum(_float(r.get("ip")) for r in rows[-3:]))
    baseline = {
        "ip": _clamp(float(baseline_ip), 15, 220),
        "era": _clamp(_weighted(rows, "era", "ip") or LEAGUE_ERA, 1.3, 8.0),
        "k9": _clamp(9 * sum(_float(r.get("so")) for r in rows[-3:]) / totals_ip, 2.0, 16.0),
        "bb9": _clamp(9 * sum(_float(r.get("bb")) for r in rows[-3:]) / totals_ip, 0.5, 8.0),
        "hr9": _clamp(9 * sum(_float(r.get("hr")) for r in rows[-3:]) / totals_ip, 0.1, 3.0),
        "starter_share": _clamp(sum(_float(r.get("starts")) for r in rows[-3:]) / max(1, sum(_float(r.get("games")) for r in rows[-3:])), 0, 1),
    }
    recent_sc = statcast[-1] if statcast else {}
    xwoba = _float(recent_sc.get("xwoba"), LEAGUE_WOBA + (baseline["era"] - LEAGUE_ERA) * 0.018)
    baseline["era"] = _clamp(0.78 * baseline["era"] + 0.22 * (LEAGUE_ERA + (xwoba - LEAGUE_WOBA) * 22), 1.5, 7.5)

    horizon = max(5, min(15, 44 - age))
    years = list(range(int(latest["season"]) + 1, int(latest["season"]) + horizon + 1))
    rng = np.random.default_rng(_seed(int(player.get("player_id", 0)), "pitcher", adjustments))
    alive = np.ones(simulations, dtype=bool)
    ip = np.full(simulations, baseline["ip"])
    era = np.full(simulations, baseline["era"])
    k9 = np.full(simulations, baseline["k9"])
    bb9 = np.full(simulations, baseline["bb9"])
    hr9 = np.full(simulations, baseline["hr9"])
    cumulative_so = np.full(simulations, sum(_float(row.get("so")) for row in rows))
    cumulative_wins = np.full(simulations, sum(_float(row.get("wins")) for row in rows))
    current_value = _actual_pitcher_value(rows)
    cumulative_value = np.full(simulations, current_value)
    season_rows = []
    path_active: list[np.ndarray] = []
    path_era: list[np.ndarray] = []

    skill = 1 + _clamp(_float(adjustments.get("skill")), -12, 12) / 100
    availability = 1 + _clamp(_float(adjustments.get("availability")), -25, 25) / 100
    longevity = _clamp(_float(adjustments.get("longevity")), -20, 20) / 100
    environment = 1 + _clamp(_float(adjustments.get("environment")), -12, 12) / 100
    talent_bonus = _clamp((LEAGUE_ERA - baseline["era"]) * 0.035 + (baseline["ip"] - 70) / 1600, -0.08, 0.12)

    for index, year in enumerate(years):
        transition_age = age + index
        prior = _prior("pitcher", transition_age)
        survival = _clamp(_float(prior["survival"]) + talent_bonus + longevity, 0.22, 0.992)
        if index == 0 and player.get("active", True):
            survival = max(survival, 0.92)
        alive &= rng.random(simulations) < survival
        common = rng.normal(0, 1, simulations)
        era = LEAGUE_ERA + (era - LEAGUE_ERA) * 0.92 + _float(prior["era_delta"]) + common * _float(prior["era_sd"]) * 0.48
        era = np.clip(LEAGUE_ERA + (era - LEAGUE_ERA) / skill, 1.30, 8.50)
        k9 = np.clip(k9 + _float(prior["k9_delta"]) + common * 0.30 + (skill - 1) * 9, 2, 16)
        bb9 = np.clip(bb9 + _float(prior["bb9_delta"]) + rng.normal(0, 0.28, simulations) - (skill - 1) * 4, 0.5, 8)
        hr9 = np.clip((hr9 + _float(prior["hr9_delta"]) + rng.normal(0, 0.12, simulations)) * environment, 0.1, 3.5)
        ip = ip * _float(prior["ip_factor"], 0.86) * np.exp(rng.normal(0, 0.25, simulations)) * availability
        ip = np.where(alive, np.clip(ip, 8, 230), 0)
        strikeouts = np.rint(ip * k9 / 9)
        wins = np.rint(ip / (18 if baseline["starter_share"] >= 0.45 else 45) * np.clip((5.0 - era) / 2.5, 0.35, 1.5))
        value = _pitcher_value(ip, era)
        cumulative_so += strikeouts
        cumulative_wins += wins
        cumulative_value += value
        active_season = ip >= 10
        path_active.append(active_season)
        path_era.append(era.copy())
        season_rows.append({
            "season": year, "age": transition_age + 1, "workload": _percentiles(ip, 1),
            "rate": _percentiles(era, 2), "rate_label": "ERA", "strikeouts": _percentiles(strikeouts, 0),
            "wins": _percentiles(wins, 0), "value": _percentiles(value, 1),
            "active_probability": round(float(np.mean(active_season) * 100), 1),
        })

    active_matrix = np.vstack(path_active)
    seasons_remaining = active_matrix.sum(axis=0)
    retirement = np.full(simulations, int(latest["season"]), dtype=float)
    for idx, year in enumerate(years):
        retirement = np.where(active_matrix[idx], year, retirement)
    current_so = sum(_float(row.get("so")) for row in rows)
    current_wins = sum(_float(row.get("wins")) for row in rows)
    milestones = []
    for threshold in [1000, 1500, 2000, 2500, 3000, 3500]:
        if threshold > current_so and len(milestones) < 2:
            milestones.append(_milestone(f"{threshold:,} strikeouts", threshold, cumulative_so, current_so))
    for threshold in [100, 150, 200, 250, 300]:
        if threshold > current_wins and len(milestones) < 4:
            milestones.append(_milestone(f"{threshold} wins", threshold, cumulative_wins, current_wins))
    for threshold in [30, 50, 70, 90]:
        if threshold > current_value and len(milestones) < 5:
            milestones.append(_milestone(f"{threshold} CURVE Value", threshold, cumulative_value, current_value, "CV"))

    recent_trend = (_float(rows[-2].get("era")) - _float(rows[-1].get("era"))) if len(rows) >= 2 else 0
    reasons = [
        {"label": "Age curve", "impact": "positive" if age <= 27 else "negative", "detail": f"Age {age} is matched to {int(_prior('pitcher', age)['sample']):,} comparable modern pitcher-seasons."},
        {"label": "Contact quality", "impact": "positive" if xwoba <= LEAGUE_WOBA else "negative", "detail": f"Statcast opponent xwOBA is {xwoba:.3f}." if statcast else "Statcast was unavailable, so uncertainty is wider."},
        {"label": "Recent direction", "impact": "positive" if recent_trend >= 0 else "negative", "detail": f"Recent ERA direction improved by {recent_trend:+.2f}; the model applies regression."},
        {"label": "Role security", "impact": "positive" if baseline["ip"] >= 110 else "neutral", "detail": f"The current workload baseline is {baseline['ip']:.0f} IP with a {baseline['starter_share']:.0%} start share."},
    ]
    whiff = _float(recent_sc.get("whiff_percent"), 25)
    skills = [
        {"label": "Stuff", "grade": _grade(50 + (baseline["k9"] - 8.5) * 5 + (whiff - 25) * 0.7)},
        {"label": "Command", "grade": _grade(50 + (3.2 - baseline["bb9"]) * 7)},
        {"label": "Suppression", "grade": _grade(50 + (LEAGUE_ERA - baseline["era"]) * 8)},
        {"label": "Contact", "grade": _grade(50 + (LEAGUE_WOBA - xwoba) * 190)},
        {"label": "Availability", "grade": _grade(50 + (baseline["ip"] - 90) / 3)},
    ]
    confidence_score = min(94, 45 + min(28, len(rows) * 4) + (14 if statcast else 0) + (7 if baseline["ip"] >= 70 else 0))
    survival_3 = round(float(np.mean(active_matrix[min(2, len(years) - 1)]) * 100), 1)
    best_actual_era = min((_float(row.get("era")) for row in rows[-3:]), default=baseline["era"])
    best_future_era = np.min(np.where(active_matrix, np.vstack(path_era), np.inf), axis=0)
    second_peak = round(float(np.mean(best_future_era <= best_actual_era - 0.25) * 100), 1)
    return {
        "baseline": {key: round(value, 3 if key not in {"ip", "era", "k9", "bb9", "hr9"} else 2) for key, value in baseline.items()},
        "seasons": season_rows,
        "summary": {
            "remaining_seasons": _percentiles(seasons_remaining, 0), "retirement_year": _percentiles(retirement, 0),
            "remaining_value": _percentiles(cumulative_value - current_value, 1), "career_value": _percentiles(cumulative_value, 1),
            "career_strikeouts": _percentiles(cumulative_so, 0), "career_wins": _percentiles(cumulative_wins, 0),
            "three_year_survival": survival_3, "second_peak_probability": second_peak,
            "cliff_risk": round(100 - survival_3, 1),
        },
        "milestones": milestones, "comparables": _similarity_pitcher(age, baseline), "drivers": reasons,
        "skills": skills, "confidence": {"score": confidence_score, "label": "High" if confidence_score >= 80 else "Solid" if confidence_score >= 65 else "Exploratory"},
        "metric_labels": {"workload": "IP", "rate": "ERA", "count": "SO"},
    }


def simulate_career(
    player: dict[str, Any],
    history: dict[str, list[dict[str, Any]]],
    statcast: list[dict[str, Any]],
    *,
    requested_role: str = "auto",
    adjustments: dict[str, float] | None = None,
    simulations: int = 5000,
) -> dict[str, Any]:
    roles = available_roles(history)
    role = choose_role(history, requested_role)
    rows = history.get(role) or []
    if not rows:
        raise ValueError("This player does not have enough MLB season history for a simulation yet.")
    adjustments = adjustments or {}
    simulations = int(_clamp(simulations, 1000, 10000))
    core = _hitter_simulation(player, rows, statcast, adjustments, simulations) if role == "hitter" else _pitcher_simulation(player, rows, statcast, adjustments, simulations)
    age = _current_age(player, rows)
    core.update({
        "model": {
            "name": "CURVE Engine", "version": MODEL_VERSION, "simulations": simulations,
            "training_window": _priors()["training_window"], "training_source": _priors()["training_source"],
            "method": "Recency-weighted talent, empirical age transitions, career survival, historical twins, and correlated Monte Carlo outcomes.",
            "backtest": _priors()["backtest"],
        },
        "player": {**player, "age": age}, "role": role, "available_roles": roles,
        "history": history, "role_history": rows, "statcast": statcast, "adjustments": adjustments,
    })
    return core


def demo_inputs() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    player = {
        "player_id": 999101, "full_name": "Mateo Vega", "active": True, "position": "CF",
        "team": "Pacific Stars", "birth_date": "1999-04-12", "bats": "L", "throws": "R",
        "demo": True,
    }
    history = {
        "hitter": [
            {"season": 2022, "age": 23, "team": "PAC", "games": 118, "pa": 438, "ab": 392, "runs": 62, "hits": 99, "doubles": 21, "triples": 5, "hr": 15, "rbi": 54, "bb": 39, "so": 109, "sb": 19, "cs": 5, "avg": .253, "obp": .326, "slg": .446, "ops": .772},
            {"season": 2023, "age": 24, "team": "PAC", "games": 148, "pa": 612, "ab": 548, "runs": 91, "hits": 151, "doubles": 30, "triples": 7, "hr": 24, "rbi": 78, "bb": 55, "so": 128, "sb": 27, "cs": 6, "avg": .276, "obp": .347, "slg": .487, "ops": .834},
            {"season": 2024, "age": 25, "team": "PAC", "games": 155, "pa": 658, "ab": 579, "runs": 104, "hits": 170, "doubles": 34, "triples": 8, "hr": 31, "rbi": 91, "bb": 68, "so": 119, "sb": 32, "cs": 7, "avg": .294, "obp": .369, "slg": .541, "ops": .910},
            {"season": 2025, "age": 26, "team": "PAC", "games": 157, "pa": 671, "ab": 588, "runs": 109, "hits": 171, "doubles": 36, "triples": 6, "hr": 35, "rbi": 101, "bb": 72, "so": 125, "sb": 28, "cs": 6, "avg": .291, "obp": .367, "slg": .551, "ops": .918},
            {"season": 2026, "age": 27, "team": "PAC", "games": 121, "pa": 526, "ab": 461, "runs": 84, "hits": 132, "doubles": 27, "triples": 5, "hr": 29, "rbi": 82, "bb": 57, "so": 96, "sb": 21, "cs": 5, "avg": .286, "obp": .365, "slg": .556, "ops": .921},
        ],
        "pitcher": [],
    }
    statcast = [
        {"season": 2024, "pa": 658, "k_percent": 18.1, "bb_percent": 10.3, "woba": .389, "xwoba": .381, "barrel_percent": 13.4, "hard_hit_percent": 50.1, "ev50": 103.2, "exit_velocity": 92.0, "launch_angle": 14.1},
        {"season": 2025, "pa": 671, "k_percent": 18.6, "bb_percent": 10.7, "woba": .391, "xwoba": .386, "barrel_percent": 14.1, "hard_hit_percent": 51.8, "ev50": 103.8, "exit_velocity": 92.4, "launch_angle": 15.0},
        {"season": 2026, "pa": 526, "k_percent": 18.3, "bb_percent": 10.8, "woba": .393, "xwoba": .389, "barrel_percent": 14.5, "hard_hit_percent": 52.2, "ev50": 104.0, "exit_velocity": 92.7, "launch_angle": 15.3},
    ]
    return player, history, statcast
