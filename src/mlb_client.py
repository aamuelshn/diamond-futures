from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import MLB_PEOPLE_SEARCH_URL, MLB_PERSON_URL
from .models import PlayerCandidate


class PlayerLookupError(RuntimeError):
    """Raised when MLB's player lookup cannot be completed."""


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "StatcastHomeRunCurve/1.0 (educational project)",
            "Accept": "application/json",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _candidate_from_person(person: dict[str, Any]) -> PlayerCandidate:
    position = person.get("primaryPosition") or {}
    team = person.get("currentTeam") or {}
    bat_side = person.get("batSide") or {}
    pitch_hand = person.get("pitchHand") or {}
    return PlayerCandidate(
        player_id=int(person["id"]),
        full_name=str(person.get("fullName") or person.get("fullFMLName") or person["id"]),
        active=person.get("active"),
        position=position.get("abbreviation") or position.get("name"),
        team=team.get("name"),
        debut_date=_parse_date(person.get("mlbDebutDate")),
        last_played_date=_parse_date(person.get("lastPlayedDate")),
        birth_date=_parse_date(person.get("birthDate")),
        bats=bat_side.get("code") or bat_side.get("description"),
        throws=pitch_hand.get("code") or pitch_hand.get("description"),
        height=person.get("height"),
        weight=int(person["weight"]) if person.get("weight") is not None else None,
    )


def _similarity(query: str, name: str) -> float:
    return SequenceMatcher(None, query.casefold().strip(), name.casefold().strip()).ratio()


def search_players(query: str, *, timeout: int = 20) -> list[PlayerCandidate]:
    """Search MLB's people endpoint and return likely player matches."""
    clean = " ".join(query.split())
    if len(clean) < 2:
        return []

    session = _session()
    attempts = [clean]
    if " " in clean:
        attempts.append(clean.split()[-1])

    people: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for name in attempts:
        try:
            response = session.get(
                MLB_PEOPLE_SEARCH_URL,
                params={"names": name},
                timeout=(8, timeout),
            )
            response.raise_for_status()
            payload = response.json()
            for person in payload.get("people", []):
                if person.get("id") is not None:
                    people[int(person["id"])] = person
            if people:
                break
        except (requests.RequestException, ValueError) as exc:
            errors.append(str(exc))

    if not people and errors:
        raise PlayerLookupError(
            "Player search could not reach MLB's lookup service. "
            "Check your internet connection or use the manual MLBAM ID option."
        )

    candidates = [_candidate_from_person(person) for person in people.values()]
    candidates.sort(
        key=lambda candidate: (
            _similarity(clean, candidate.full_name),
            candidate.active is True,
            candidate.last_played_date or date.min,
        ),
        reverse=True,
    )
    return candidates[:15]


def get_player_detail(player_id: int, *, timeout: int = 20) -> PlayerCandidate:
    """Retrieve a fuller player record after a search result is selected."""
    session = _session()
    try:
        response = session.get(
            MLB_PERSON_URL.format(player_id=int(player_id)),
            params={"hydrate": "currentTeam"},
            timeout=(8, timeout),
        )
        response.raise_for_status()
        people = response.json().get("people", [])
    except (requests.RequestException, ValueError) as exc:
        raise PlayerLookupError(
            f"Could not retrieve details for MLBAM {player_id}: {exc}"
        ) from exc

    if not people:
        raise PlayerLookupError(f"MLBAM {player_id} did not return a player record.")
    return _candidate_from_person(people[0])
