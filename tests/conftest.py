from __future__ import annotations

import pytest

from pllmenary.config import (
    BudgetsAndLimits,
    Config,
    Infrastructure,
    LoopControl,
    ModelRef,
    ParticipantSpec,
    RolesAndModels,
)


def make_config(**overrides) -> Config:
    roles = RolesAndModels(
        chairman=ModelRef(provider="mock", model="chair-model"),
        participants=[
            ParticipantSpec(model=ModelRef(provider="mock", model="p1"), count=1),
            ParticipantSpec(model=ModelRef(provider="mock", model="p2"), count=1),
        ],
    )
    loop = LoopControl(max_iterations=3)
    budgets = BudgetsAndLimits(
        overall_timeout_seconds=60,
        synthesis_timeout_seconds=30,
        per_call_timeout_seconds=10,
        stall_timeout_seconds=10,
        max_tokens_per_call=256,
    )
    infrastructure = Infrastructure(message_bus="in_process", storage="in_memory")
    base = Config(roles=roles, loop=loop, budgets=budgets, infrastructure=infrastructure)
    return base.model_copy(update=overrides) if overrides else base


@pytest.fixture
def base_config() -> Config:
    return make_config()
