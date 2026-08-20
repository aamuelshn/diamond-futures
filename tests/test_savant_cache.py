from __future__ import annotations

from datetime import date

import pandas as pd

from src import savant_client


CSV = """game_date,events,game_type,batter,hit_distance_sc,launch_speed,launch_angle,game_pk,at_bat_number,pitch_number
2024-04-01,home_run,R,660271,430,111.2,27,1,1,3
2024-04-02,home_run,R,660271,401,106.4,31,2,1,2
"""


class FakeResponse:
    text = CSV

    def raise_for_status(self):
        return None


class CountingSession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return FakeResponse()


def test_season_download_is_cached(monkeypatch, tmp_path) -> None:
    session = CountingSession()
    monkeypatch.setattr(savant_client, "_session", lambda: session)

    first = savant_client.fetch_savant_season(
        660271,
        2024,
        ["R"],
        cache_dir=tmp_path,
        today=date(2026, 7, 28),
    )
    second = savant_client.fetch_savant_season(
        660271,
        2024,
        ["R"],
        cache_dir=tmp_path,
        today=date(2026, 7, 28),
    )

    assert session.calls == 1
    assert len(first) == 2
    pd.testing.assert_frame_equal(first, second)
