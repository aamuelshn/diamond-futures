from __future__ import annotations

from src import mlb_client


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def get(self, url, params=None, timeout=None):
        return FakeResponse(
            {
                "people": [
                    {
                        "id": 660271,
                        "fullName": "Shohei Ohtani",
                        "active": True,
                        "primaryPosition": {"abbreviation": "DH"},
                        "currentTeam": {"name": "Los Angeles Dodgers"},
                        "mlbDebutDate": "2018-03-29",
                    },
                    {
                        "id": 999999,
                        "fullName": "A Different Name",
                        "active": False,
                    },
                ]
            }
        )


def test_player_search_ranks_exact_name_first(monkeypatch) -> None:
    monkeypatch.setattr(mlb_client, "_session", lambda: FakeSession())
    results = mlb_client.search_players("Shohei Ohtani")
    assert results[0].player_id == 660271
    assert results[0].position == "DH"
    assert results[0].debut_date.year == 2018
