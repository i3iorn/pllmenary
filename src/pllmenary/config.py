"""Typed configuration object, defaults, presets, validation.

Spec: "Configuration".
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionMode(str, Enum):
    SINGLE_THREADED = "single_threaded"
    MULTITHREADED = "multithreaded"
    MULTIPROCESS = "multiprocess"


class CancelBehavior(str, Enum):
    HARD_STOP = "hard_stop"
    SYNTHESIZE = "synthesize"


class TimeoutBehavior(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class TimeoutScope(str, Enum):
    ITERATIONS = "iterations"
    ITERATIONS_AND_SYNTHESIS = "iterations_and_synthesis"


class RunStateRetention(str, Enum):
    PURGE_ON_END = "purge_on_end"
    KEEP = "keep"


class ModelRef(BaseModel):
    """Names a model: provider, model name, and how to find its credentials.

    ``settings`` holds the name of a credential variable, never the
    credential itself (see spec: Model support).
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    credential_env: str | None = None
    endpoint: str | None = None
    settings: dict[str, str] = Field(
        default_factory=dict,
        description="Adapter-specific settings, e.g. the mock provider's script selector.",
    )
    context_window: int | None = Field(
        default=None,
        description=(
            "Used only when the adapter cannot report its own context "
            "window (see spec: Configuration - Context threshold)."
        ),
    )

    @property
    def account_key(self) -> str:
        """Provider together with its credentials/endpoint (see spec: Rate limits)."""
        return f"{self.provider}:{self.credential_env or ''}:{self.endpoint or ''}"


class ParticipantSpec(BaseModel):
    """One configured panel member, possibly repeated as several instances."""

    model_config = ConfigDict(frozen=True)

    model: ModelRef
    count: int = Field(default=1, ge=1)
    persona: str | None = None


class Temperatures(BaseModel):
    """Per-role temperatures, on top of per-model overrides."""

    model_config = ConfigDict(frozen=True)

    participants: float | None = None
    chairman: float | None = None
    summarizer: float | None = None
    per_model: dict[str, float] = Field(default_factory=dict)


class RolesAndModels(BaseModel):
    model_config = ConfigDict(frozen=True)

    chairman: ModelRef
    participants: list[ParticipantSpec]
    summarizer: ModelRef | None = None
    temperatures: Temperatures = Field(default_factory=Temperatures)

    @property
    def panel_size(self) -> int:
        return sum(p.count for p in self.participants)

    @model_validator(mode="after")
    def _at_least_one_participant(self) -> "RolesAndModels":
        if self.panel_size < 1:
            raise ValueError("at least one participant is required")
        return self


class LoopControl(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_iterations: int = Field(gt=0)
    min_round: int = Field(default=0, ge=0)
    peer_to_peer: bool = True
    pairing: str = "round_robin"
    challenger: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.MULTIPROCESS
    cancel_behavior: CancelBehavior = CancelBehavior.HARD_STOP
    context_threshold: float = Field(default=0.75, gt=0, le=1)


class BackoffSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_seconds: float = Field(default=1.0, gt=0)
    factor: float = Field(default=2.0, ge=1)
    max_seconds: float = Field(default=60.0, gt=0)


class RateLimit(BaseModel):
    """Caps on concurrent calls and requests per minute for one provider account."""

    model_config = ConfigDict(frozen=True)

    max_concurrency: int | None = Field(default=None, ge=1)
    requests_per_minute: float | None = Field(default=None, gt=0)


class BudgetsAndLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall_timeout_seconds: float = Field(gt=0)
    timeout_behavior: TimeoutBehavior = TimeoutBehavior.SOFT
    timeout_scope: TimeoutScope = TimeoutScope.ITERATIONS
    synthesis_timeout_seconds: float = Field(gt=0)
    per_call_timeout_seconds: float = Field(gt=0)
    stall_timeout_seconds: float = Field(gt=0)
    stall_limit: int = Field(default=2, ge=1)
    retry_limit: int = Field(default=3, ge=0)
    backoff: BackoffSchedule = Field(default_factory=BackoffSchedule)
    min_panel: int = Field(default=2, ge=1)
    max_tokens_per_call: int = Field(gt=0)
    max_tokens_per_call_overrides: dict[str, int] = Field(default_factory=dict)
    token_budget: int | None = Field(default=None, ge=0)
    cost_budget: float | None = Field(default=None, ge=0)
    cost_currency: str | None = None
    rate_limits: dict[str, RateLimit] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _cost_budget_needs_currency(self) -> "BudgetsAndLimits":
        if self.cost_budget is not None and not self.cost_currency:
            raise ValueError("cost_budget requires cost_currency")
        return self


class Infrastructure(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_bus: str
    storage: str
    run_state_retention: RunStateRetention = RunStateRetention.PURGE_ON_END
    resume_limit: int = Field(default=3, ge=0)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _storage_required(self) -> "Infrastructure":
        if not self.storage:
            raise ValueError(
                "storage is required and has no default (see spec: Infrastructure)"
            )
        return self


class Config(BaseModel):
    """The system's full configuration object (see spec: Configuration)."""

    model_config = ConfigDict(frozen=True)

    roles: RolesAndModels
    loop: LoopControl
    budgets: BudgetsAndLimits
    infrastructure: Infrastructure

    @model_validator(mode="after")
    def _min_panel_reachable(self) -> "Config":
        if self.roles.panel_size < self.budgets.min_panel:
            raise ValueError(
                "configured panel size is smaller than the minimum panel "
                f"({self.roles.panel_size} < {self.budgets.min_panel})"
            )
        return self

    @model_validator(mode="after")
    def _cost_budget_needs_prices(self) -> "Config":
        # A full price check requires the model registry (phase 1); this
        # only enforces the shape of the rule the spec states.
        return self


class PresetStore(BaseModel):
    """Named configurations for reuse (see spec: Configuration - Presets)."""

    model_config = ConfigDict(frozen=True)

    presets: dict[str, Config] = Field(default_factory=dict)

    def get(self, name: str) -> Config:
        try:
            return self.presets[name]
        except KeyError as exc:
            raise KeyError(f"no such preset: {name!r}") from exc

    def with_preset(self, name: str, config: Config) -> "PresetStore":
        return PresetStore(presets={**self.presets, name: config})


def fast_preset(base: Config) -> Config:
    """A preset with a single iteration and no peer-to-peer round."""
    return base.model_copy(
        update={
            "loop": base.loop.model_copy(
                update={"max_iterations": 1, "peer_to_peer": False}
            )
        }
    )
