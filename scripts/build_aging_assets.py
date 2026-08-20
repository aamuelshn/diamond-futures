"""Build compact CURVE Engine training assets from the SABR Lahman database.

The public site reads only the small generated JSON/GZIP files. Re-run this
script after downloading Batting.csv, Pitching.csv, and People.csv from the
SABR Lahman Database (or its byte-for-byte CSV mirror).
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _weighted_median(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return 0.0
    ordered = pd.DataFrame({"v": values[valid], "w": weights[valid]}).sort_values("v")
    cutoff = ordered["w"].sum() / 2
    return float(ordered.loc[ordered["w"].cumsum() >= cutoff, "v"].iloc[0])


def _robust_sd(values: pd.Series, floor: float) -> float:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 8:
        return floor
    q25, q75 = clean.quantile([0.25, 0.75])
    return float(max(floor, (q75 - q25) / 1.349))


def _people(path: Path) -> pd.DataFrame:
    people = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    people["birthYear"] = pd.to_numeric(people["birthYear"], errors="coerce")
    people["name"] = (
        people["nameFirst"].fillna("").astype(str).str.strip()
        + " "
        + people["nameLast"].fillna("").astype(str).str.strip()
    ).str.strip()
    return people[["playerID", "birthYear", "name", "bats", "throws"]]


def _batting(path: Path, people: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    numeric = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "HBP", "SH", "SF"]
    for column in numeric:
        raw[column] = _number(raw[column])
    season = raw.groupby(["playerID", "yearID"], as_index=False)[numeric].sum()
    season = season.merge(people, on="playerID", how="left")
    season["age"] = season["yearID"] - season["birthYear"]
    season["pa"] = season["AB"] + season["BB"] + season["HBP"] + season["SF"] + season["SH"]
    season["obp"] = (season["H"] + season["BB"] + season["HBP"]) / (season["AB"] + season["BB"] + season["HBP"] + season["SF"]).replace(0, np.nan)
    season["slg"] = (season["H"] + season["2B"] + 2 * season["3B"] + 3 * season["HR"]) / season["AB"].replace(0, np.nan)
    season["ops"] = season["obp"] + season["slg"]
    for stat, out in [("HR", "hr_rate"), ("SO", "k_rate"), ("BB", "bb_rate"), ("SB", "sb_rate")]:
        season[out] = season[stat] / season["pa"].replace(0, np.nan)
    return season.loc[(season["yearID"] >= 1980) & season["age"].between(18, 46)].sort_values(["playerID", "yearID"])


def _pitching(path: Path, people: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    numeric = ["W", "L", "G", "GS", "SV", "IPouts", "H", "ER", "HR", "BB", "SO", "BFP"]
    for column in numeric:
        raw[column] = _number(raw[column])
    season = raw.groupby(["playerID", "yearID"], as_index=False)[numeric].sum()
    season = season.merge(people, on="playerID", how="left")
    season["age"] = season["yearID"] - season["birthYear"]
    season["ip"] = season["IPouts"] / 3
    season["era"] = 9 * season["ER"] / season["ip"].replace(0, np.nan)
    season["k9"] = 9 * season["SO"] / season["ip"].replace(0, np.nan)
    season["bb9"] = 9 * season["BB"] / season["ip"].replace(0, np.nan)
    season["hr9"] = 9 * season["HR"] / season["ip"].replace(0, np.nan)
    season["starter_share"] = season["GS"] / season["G"].replace(0, np.nan)
    return season.loc[(season["yearID"] >= 1980) & season["age"].between(18, 47)].sort_values(["playerID", "yearID"])


def _hitter_priors(frame: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    next_frame = frame[["playerID", "yearID", "age", "pa", "ops", "hr_rate", "k_rate", "bb_rate", "sb_rate"]].copy()
    next_frame["yearID"] -= 1
    next_frame = next_frame.rename(columns={c: f"next_{c}" for c in ["age", "pa", "ops", "hr_rate", "k_rate", "bb_rate", "sb_rate"]})
    paired = frame.merge(next_frame, on=["playerID", "yearID"], how="left")
    priors: dict[str, dict[str, float | int]] = {}
    for age in range(20, 43):
        eligible = paired.loc[(paired["age"].round() == age) & (paired["pa"] >= 100)].copy()
        continued = eligible.loc[eligible["next_pa"] >= 50].copy()
        if len(continued) < 20:
            continue
        weights = np.sqrt(continued["pa"].clip(upper=700))
        ops_delta = continued["next_ops"] - continued["ops"]
        hr_ratio = (continued["next_hr_rate"] + 0.002) / (continued["hr_rate"] + 0.002)
        priors[str(age)] = {
            "sample": int(len(eligible)),
            "survival": round(float(len(continued) / max(1, len(eligible))), 4),
            "pa_factor": round(_weighted_median((continued["next_pa"] / continued["pa"]).clip(0.15, 1.5), weights), 4),
            "ops_delta": round(_weighted_median(ops_delta.clip(-0.25, 0.25), weights), 4),
            "ops_sd": round(_robust_sd(ops_delta, 0.035), 4),
            "hr_factor": round(_weighted_median(hr_ratio.clip(0.25, 2.0), weights), 4),
            "k_delta": round(_weighted_median((continued["next_k_rate"] - continued["k_rate"]).clip(-0.12, 0.12), weights), 4),
            "bb_delta": round(_weighted_median((continued["next_bb_rate"] - continued["bb_rate"]).clip(-0.08, 0.08), weights), 4),
            "speed_factor": round(_weighted_median(((continued["next_sb_rate"] + 0.002) / (continued["sb_rate"] + 0.002)).clip(0.1, 2.0), weights), 4),
        }
    return priors


def _pitcher_priors(frame: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    columns = ["playerID", "yearID", "age", "ip", "era", "k9", "bb9", "hr9"]
    next_frame = frame[columns].copy()
    next_frame["yearID"] -= 1
    next_frame = next_frame.rename(columns={c: f"next_{c}" for c in ["age", "ip", "era", "k9", "bb9", "hr9"]})
    paired = frame.merge(next_frame, on=["playerID", "yearID"], how="left")
    priors: dict[str, dict[str, float | int]] = {}
    for age in range(20, 44):
        eligible = paired.loc[(paired["age"].round() == age) & (paired["ip"] >= 25)].copy()
        continued = eligible.loc[eligible["next_ip"] >= 10].copy()
        if len(continued) < 20:
            continue
        weights = np.sqrt(continued["ip"].clip(upper=220))
        era_delta = continued["next_era"] - continued["era"]
        priors[str(age)] = {
            "sample": int(len(eligible)),
            "survival": round(float(len(continued) / max(1, len(eligible))), 4),
            "ip_factor": round(_weighted_median((continued["next_ip"] / continued["ip"]).clip(0.1, 1.7), weights), 4),
            "era_delta": round(_weighted_median(era_delta.clip(-2.5, 2.5), weights), 4),
            "era_sd": round(_robust_sd(era_delta, 0.45), 4),
            "k9_delta": round(_weighted_median((continued["next_k9"] - continued["k9"]).clip(-4, 4), weights), 4),
            "bb9_delta": round(_weighted_median((continued["next_bb9"] - continued["bb9"]).clip(-2.5, 2.5), weights), 4),
            "hr9_delta": round(_weighted_median((continued["next_hr9"] - continued["hr9"]).clip(-1.5, 1.5), weights), 4),
        }
    return priors


def _backtest(batting: pd.DataFrame, pitching: pd.DataFrame) -> dict[str, object]:
    """Run a fixed 2016-2024 holdout using priors learned through 2015."""
    hitter_train = _hitter_priors(batting.loc[batting["yearID"] <= 2015])
    hitter_next = batting[["playerID", "yearID", "pa", "ops"]].copy()
    hitter_next["yearID"] -= 1
    hitter_next = hitter_next.rename(columns={"pa": "next_pa", "ops": "next_ops"})
    hitter_test = batting.merge(hitter_next, on=["playerID", "yearID"], how="left")
    hitter_test = hitter_test.loc[hitter_test["yearID"].between(2016, 2024) & (hitter_test["pa"] >= 100)].copy()
    hitter_test["prior"] = hitter_test["age"].round().astype(int).astype(str).map(hitter_train)
    hitter_test = hitter_test.loc[hitter_test["prior"].notna()]
    hitter_test["survived"] = hitter_test["next_pa"].fillna(0) >= 50
    hitter_test["survival_p"] = hitter_test["prior"].apply(lambda value: value["survival"])
    hitter_cont = hitter_test.loc[hitter_test["survived"] & hitter_test["next_ops"].notna()].copy()
    hitter_cont["prediction"] = hitter_cont.apply(lambda row: row["ops"] + row["prior"]["ops_delta"], axis=1)
    hitter_cont["radius"] = hitter_cont["prior"].apply(lambda value: 1.282 * value["ops_sd"])

    pitcher_train = _pitcher_priors(pitching.loc[pitching["yearID"] <= 2015])
    pitcher_next = pitching[["playerID", "yearID", "ip", "era"]].copy()
    pitcher_next["yearID"] -= 1
    pitcher_next = pitcher_next.rename(columns={"ip": "next_ip", "era": "next_era"})
    pitcher_test = pitching.merge(pitcher_next, on=["playerID", "yearID"], how="left")
    pitcher_test = pitcher_test.loc[pitcher_test["yearID"].between(2016, 2024) & (pitcher_test["ip"] >= 25)].copy()
    pitcher_test["prior"] = pitcher_test["age"].round().astype(int).astype(str).map(pitcher_train)
    pitcher_test = pitcher_test.loc[pitcher_test["prior"].notna()]
    pitcher_test["survived"] = pitcher_test["next_ip"].fillna(0) >= 10
    pitcher_test["survival_p"] = pitcher_test["prior"].apply(lambda value: value["survival"])
    pitcher_cont = pitcher_test.loc[pitcher_test["survived"] & pitcher_test["next_era"].notna()].copy()
    pitcher_cont["prediction"] = pitcher_cont.apply(lambda row: row["era"] + row["prior"]["era_delta"], axis=1)
    pitcher_cont["radius"] = pitcher_cont["prior"].apply(lambda value: 1.282 * value["era_sd"])

    return {
        "holdout": "2016-2024",
        "hitter": {
            "player_seasons": int(len(hitter_test)),
            "one_year_metric": "OPS",
            "mae": round(float((hitter_cont["prediction"] - hitter_cont["next_ops"]).abs().mean()), 3),
            "naive_mae": round(float((hitter_cont["ops"] - hitter_cont["next_ops"]).abs().mean()), 3),
            "interval_80_coverage": round(float(((hitter_cont["next_ops"] - hitter_cont["prediction"]).abs() <= hitter_cont["radius"]).mean() * 100), 1),
            "survival_brier": round(float(((hitter_test["survival_p"] - hitter_test["survived"].astype(float)) ** 2).mean()), 3),
        },
        "pitcher": {
            "player_seasons": int(len(pitcher_test)),
            "one_year_metric": "ERA",
            "mae": round(float((pitcher_cont["prediction"] - pitcher_cont["next_era"]).abs().mean()), 2),
            "naive_mae": round(float((pitcher_cont["era"] - pitcher_cont["next_era"]).abs().mean()), 2),
            "interval_80_coverage": round(float(((pitcher_cont["next_era"] - pitcher_cont["prediction"]).abs() <= pitcher_cont["radius"]).mean() * 100), 1),
            "survival_brier": round(float(((pitcher_test["survival_p"] - pitcher_test["survived"].astype(float)) ** 2).mean()), 3),
        },
    }


def _hitter_comps(frame: pd.DataFrame) -> list[dict[str, object]]:
    eligible = frame.loc[(frame["pa"] >= 200) & frame["age"].between(20, 40)].copy()
    totals = frame.groupby("playerID")[["HR", "H", "pa"]].sum().rename(columns={"HR": "career_hr", "H": "career_hits", "pa": "career_pa"})
    last_year = frame.groupby("playerID")["yearID"].max().rename("last_year")
    eligible = eligible.merge(totals, on="playerID").merge(last_year, on="playerID")
    eligible = eligible.loc[eligible["last_year"] <= 2023]
    eligible["next_seasons"] = eligible["last_year"] - eligible["yearID"]
    records: list[dict[str, object]] = []
    for row in eligible.itertuples(index=False):
        records.append({
            "id": row.playerID, "name": row.name, "year": int(row.yearID), "age": int(round(row.age)),
            "pa": int(round(row.pa)), "ops": round(float(row.ops), 3), "hr_rate": round(float(row.hr_rate), 4),
            "k_rate": round(float(row.k_rate), 4), "bb_rate": round(float(row.bb_rate), 4), "sb_rate": round(float(row.sb_rate), 4),
            "career_hr": int(round(row.career_hr)), "career_hits": int(round(row.career_hits)), "next_seasons": int(max(0, row.next_seasons)),
        })
    return records


def _pitcher_comps(frame: pd.DataFrame) -> list[dict[str, object]]:
    eligible = frame.loc[(frame["ip"] >= 40) & frame["age"].between(20, 41)].copy()
    totals = frame.groupby("playerID")[["SO", "W", "IPouts"]].sum().rename(columns={"SO": "career_so", "W": "career_wins", "IPouts": "career_outs"})
    last_year = frame.groupby("playerID")["yearID"].max().rename("last_year")
    eligible = eligible.merge(totals, on="playerID").merge(last_year, on="playerID")
    eligible = eligible.loc[eligible["last_year"] <= 2023]
    eligible["next_seasons"] = eligible["last_year"] - eligible["yearID"]
    records: list[dict[str, object]] = []
    for row in eligible.itertuples(index=False):
        records.append({
            "id": row.playerID, "name": row.name, "year": int(row.yearID), "age": int(round(row.age)),
            "ip": round(float(row.ip), 1), "era": round(float(row.era), 2), "k9": round(float(row.k9), 2),
            "bb9": round(float(row.bb9), 2), "hr9": round(float(row.hr9), 2), "starter_share": round(float(row.starter_share), 3),
            "career_so": int(round(row.career_so)), "career_wins": int(round(row.career_wins)), "next_seasons": int(max(0, row.next_seasons)),
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batting", type=Path, required=True)
    parser.add_argument("--pitching", type=Path, required=True)
    parser.add_argument("--people", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    people = _people(args.people)
    batting = _batting(args.batting, people)
    pitching = _pitching(args.pitching, people)

    priors = {
        "version": "curve-2026.1",
        "training_source": "SABR Lahman Database 1871-2025",
        "training_window": "1980-2025",
        "hitter": _hitter_priors(batting),
        "pitcher": _pitcher_priors(pitching),
        "backtest": _backtest(batting, pitching),
    }
    (args.output / "aging_priors.json").write_text(json.dumps(priors, separators=(",", ":")), encoding="utf-8")

    comps = {"hitter": _hitter_comps(batting), "pitcher": _pitcher_comps(pitching)}
    with gzip.open(args.output / "historical_comps.json.gz", "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(comps, handle, separators=(",", ":"))

    print(f"Wrote {len(comps['hitter']):,} hitter and {len(comps['pitcher']):,} pitcher age-seasons.")


if __name__ == "__main__":
    main()
