"""Provider and Model protocols, request/response types, error taxonomy.

Spec: "Model support". Only signatures are defined here; concrete adapters
implement them. Data types crossing the protocol boundary are frozen
Pydantic models so they are picklable (multiprocess mode) and safe to log.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from pllmenary.messages import Role


class ErrorKind(str, Enum):
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    PERMANENT = "permanent"


class ModelError(Exception):
    """Every model-call failure is classified as transient, timeout or permanent."""

    def __init__(self, kind: ErrorKind, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


class PromptMessage(BaseModel):
    """One role-tagged message sent to a model."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class Usage(BaseModel):
    """Token usage of one call, when the provider reports it."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int
    reported_by_provider: bool = True


class FinishReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    ERROR = "error"


class CompletionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    finish_reason: FinishReason
    usage: Usage | None = None


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_window: int
    max_output_tokens: int
    supports_system_messages: bool = True
    supports_temperature: bool = True


class Cost(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: float
    currency: str


@runtime_checkable
class Model(Protocol):
    """One model instance, reachable through its provider's adapter."""

    async def complete(
        self,
        messages: list[PromptMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> CompletionResult:
        """One attempt. The adapter never retries (see spec: Model support)."""
        ...

    def capabilities(self) -> ModelCapabilities: ...

    def estimate_input_tokens(self, messages: list[PromptMessage]) -> int: ...

    def price(self, usage: Usage) -> Cost | None: ...


@runtime_checkable
class Provider(Protocol):
    """Builds and validates a Model from a ModelRef; owns its resources."""

    async def open(self) -> None:
        """Checks credentials and model name without generating text."""
        ...

    async def aclose(self) -> None: ...
