from __future__ import annotations

import pytest
from pydantic import ValidationError

from pllmenary.config import (
    BudgetsAndLimits,
    Config,
    Infrastructure,
    LoopControl,
    ModelRef,
    ParticipantSpec,
    RolesAndModels,
    fast_preset,
)

from .conftest import make_config


def test_valid_config_builds(base_config: Config) -> None:
    assert base_config.roles.panel_size == 2
    assert base_config.loop.execution_mode.value == "multiprocess"


def test_rejects_empty_participant_list() -> None:
    with pytest.raises(ValidationError):
        RolesAndModels(chairman=ModelRef(provider="mock", model="c"), participants=[])


def test_rejects_zero_max_iterations() -> None:
    with pytest.raises(ValidationError):
        LoopControl(max_iterations=0)


def test_rejects_context_threshold_out_of_range() -> None:
    with pytest.raises(ValidationError):
        LoopControl(max_iterations=1, context_threshold=1.5)


def test_rejects_cost_budget_without_currency() -> None:
    with pytest.raises(ValidationError):
        BudgetsAndLimits(
            overall_timeout_seconds=1,
            synthesis_timeout_seconds=1,
            per_call_timeout_seconds=1,
            stall_timeout_seconds=1,
            max_tokens_per_call=1,
            cost_budget=10.0,
        )


def test_rejects_missing_storage() -> None:
    with pytest.raises(ValidationError):
        Infrastructure(message_bus="in_process", storage="")


def test_rejects_panel_smaller_than_min_panel() -> None:
    base = make_config()
    with pytest.raises(ValidationError):
        Config(
            roles=base.roles,
            loop=base.loop,
            budgets=BudgetsAndLimits(
                **{**base.budgets.model_dump(exclude={"min_panel"}), "min_panel": 5}
            ),
            infrastructure=base.infrastructure,
        )


def test_participant_count_allows_repeated_model() -> None:
    roles = RolesAndModels(
        chairman=ModelRef(provider="mock", model="c"),
        participants=[
            ParticipantSpec(model=ModelRef(provider="mock", model="p"), count=3),
        ],
    )
    assert roles.panel_size == 3


def test_fast_preset_disables_peer_to_peer(base_config: Config) -> None:
    preset = fast_preset(base_config)
    assert preset.loop.max_iterations == 1
    assert preset.loop.peer_to_peer is False
    # the original config is untouched (frozen models)
    assert base_config.loop.max_iterations == 3


def test_config_is_frozen(base_config: Config) -> None:
    with pytest.raises(ValidationError):
        base_config.loop.max_iterations = 5  # type: ignore[misc]
