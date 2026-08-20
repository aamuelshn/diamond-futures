from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

from src.savant_client import build_game_type_filter, build_savant_params, build_savant_url


def test_game_type_filter_has_savant_delimiters() -> None:
    assert build_game_type_filter(["R", "PO"]) == "R|PO|"


def test_query_matches_home_run_player_search() -> None:
    params = build_savant_params(
        660271,
        date(2024, 1, 1),
        date(2024, 12, 31),
        ["R"],
    )
    assert params["player_type"] == "batter"
    assert params["batters_lookup[]"] == "660271"
    assert params["hfAB"] == r"home\.\.run|"
    assert params["hfGT"] == "R|"
    assert params["type"] == "details"

    parsed = parse_qs(urlparse(build_savant_url(params)).query)
    assert parsed["batters_lookup[]"] == ["660271"]
    assert parsed["hfAB"] == [r"home\.\.run|"]
