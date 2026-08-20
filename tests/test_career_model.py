from __future__ import annotations

from src.career_model import demo_inputs, simulate_career


def test_curve_engine_is_deterministic_for_the_same_assumptions() -> None:
    player, history, statcast = demo_inputs()
    first = simulate_career(player, history, statcast, simulations=1000)
    second = simulate_career(player, history, statcast, simulations=1000)
    assert first["summary"] == second["summary"]


def test_positive_longevity_increases_median_remaining_seasons() -> None:
    player, history, statcast = demo_inputs()
    baseline = simulate_career(player, history, statcast, simulations=1000)
    longer = simulate_career(
        player,
        history,
        statcast,
        adjustments={"longevity": 15},
        simulations=1000,
    )
    assert longer["summary"]["remaining_seasons"]["p50"] >= baseline["summary"]["remaining_seasons"]["p50"]


def test_model_exposes_training_and_explanation_metadata() -> None:
    player, history, statcast = demo_inputs()
    result = simulate_career(player, history, statcast, simulations=1000)
    assert result["model"]["training_window"] == "1980-2025"
    assert result["confidence"]["score"] > 0
    assert all("detail" in driver for driver in result["drivers"])
