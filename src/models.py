from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PlayerCandidate:
    player_id: int
    full_name: str
    active: bool | None = None
    position: str | None = None
    team: str | None = None
    debut_date: date | None = None
    last_played_date: date | None = None
    birth_date: date | None = None
    bats: str | None = None
    throws: str | None = None
    height: str | None = None
    weight: int | None = None

    @property
    def label(self) -> str:
        details: list[str] = []
        if self.position:
            details.append(self.position)
        if self.team:
            details.append(self.team)
        if self.active is True:
            details.append("active")
        elif self.active is False:
            details.append("inactive")
        details.append(f"MLBAM {self.player_id}")
        return f"{self.full_name} — " + " — ".join(details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "full_name": self.full_name,
            "active": self.active,
            "position": self.position,
            "team": self.team,
            "debut_date": self.debut_date.isoformat() if self.debut_date else None,
            "last_played_date": self.last_played_date.isoformat() if self.last_played_date else None,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "bats": self.bats,
            "throws": self.throws,
            "height": self.height,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlayerCandidate":
        return cls(
            player_id=int(data["player_id"]),
            full_name=str(data["full_name"]),
            active=data.get("active"),
            position=data.get("position"),
            team=data.get("team"),
            debut_date=date.fromisoformat(data["debut_date"]) if data.get("debut_date") else None,
            last_played_date=(
                date.fromisoformat(data["last_played_date"])
                if data.get("last_played_date")
                else None
            ),
            birth_date=date.fromisoformat(data["birth_date"]) if data.get("birth_date") else None,
            bats=data.get("bats"),
            throws=data.get("throws"),
            height=data.get("height"),
            weight=int(data["weight"]) if data.get("weight") is not None else None,
        )
