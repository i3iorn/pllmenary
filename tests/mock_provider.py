"""The mock provider: the first real implementation of Provider and Model.

Spec-plan: "Mock provider". Replays scripted behavior with no network, so
every scenario runs without API keys and reproduces identically.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict

from pllmenary.config import ModelRef
from pllmenary.models import (
    CompletionResult,
    Cost,
    ErrorKind,
    FinishReason,
    ModelCapabilities,
    ModelError,
    PromptMessage,
    Usage,
)

CHARS_PER_TOKEN = 4
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class ReplyStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reply"] = "reply"
    text: str


class FailStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["fail"] = "fail"
    error_kind: ErrorKind = ErrorKind.TRANSIENT
    retry_after: float | None = None


class HangStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["hang"] = "hang"
    seconds: float = 3600.0


Step = Union[ReplyStep, FailStep, HangStep]


class ScriptRule(BaseModel):
    """One rule of a script: a model, an optional pattern and use limit, a step.

    The first matching rule that is not used up wins, then the script's
    default, and with neither the call fails with a permanent error.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    pattern: str | None = None
    limit: int | None = None
    step: Step

    def matches(self, model_name: str, last_message: str) -> bool:
        if self.model != model_name:
            return False
        if self.pattern is not None and re.search(self.pattern, last_message) is None:
            return False
        return True


class ModelRates(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_per_token: float
    output_per_token: float
    currency: str = "USD"


class Script(BaseModel):
    """An ordered list of rules, a default step, and optional per-model rates."""

    model_config = ConfigDict(frozen=True)

    rules: list[ScriptRule] = []
    default: Step | None = None
    rates: dict[str, ModelRates] = {}


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def _load_script_by_path(path: str) -> Script:
    module_name, sep, attr = path.partition(":")
    if not sep or not attr:
        raise ValueError(f"script import path must be 'module:attr', got {path!r}")
    module = importlib.import_module(module_name)
    script = getattr(module, attr)
    if not isinstance(script, Script):
        raise TypeError(f"{path} does not point at a Script")
    return script


class MockModel:
    """A model driven by a Script.

    A reply depends only on the model name and the request, so it is
    identical in every execution mode. ``times`` (the per-rule use count)
    is process-local, so a fail-then-succeed scenario is deterministic only
    within one process (see spec-plan: Mock provider).
    """

    def __init__(self, model_name: str, script: Script) -> None:
        self._model_name = model_name
        self._script = script
        self._use_counts: dict[int, int] = {}

    async def complete(
        self,
        messages: list[PromptMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> CompletionResult:
        del temperature  # ignored by the mock provider
        last_message = messages[-1].content if messages else ""
        step = self._select_step(last_message)
        if step is None:
            raise ModelError(
                ErrorKind.PERMANENT,
                f"no script rule or default matched model {self._model_name!r}",
            )
        if isinstance(step, FailStep):
            raise ModelError(
                step.error_kind,
                f"scripted failure for {self._model_name!r}",
                step.retry_after,
            )
        if isinstance(step, HangStep):
            await asyncio.sleep(step.seconds)
            raise ModelError(ErrorKind.TIMEOUT, "scripted hang was not cancelled in time")

        text = step.text
        finish_reason = FinishReason.STOP
        output_tokens = _count_tokens(text)
        if output_tokens > max_output_tokens:
            text = text[: max_output_tokens * CHARS_PER_TOKEN]
            output_tokens = max_output_tokens
            finish_reason = FinishReason.LENGTH

        usage = Usage(
            input_tokens=self.estimate_input_tokens(messages),
            output_tokens=output_tokens,
            reported_by_provider=False,
        )
        await asyncio.sleep(0)  # real latency, kept at zero for fast scripted tests
        return CompletionResult(text=text, finish_reason=finish_reason, usage=usage)

    def _select_step(self, last_message: str) -> Step | None:
        for index, rule in enumerate(self._script.rules):
            if not rule.matches(self._model_name, last_message):
                continue
            if rule.limit is not None:
                used = self._use_counts.get(index, 0)
                if used >= rule.limit:
                    continue
                self._use_counts[index] = used + 1
            return rule.step
        return self._script.default

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            context_window=DEFAULT_CONTEXT_WINDOW,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def estimate_input_tokens(self, messages: list[PromptMessage]) -> int:
        return sum(_count_tokens(m.content) for m in messages)

    def price(self, usage: Usage) -> Cost | None:
        rates = self._script.rates.get(self._model_name)
        if rates is None:
            return None
        amount = (
            usage.input_tokens * rates.input_per_token
            + usage.output_tokens * rates.output_per_token
        )
        return Cost(amount=amount, currency=rates.currency)


class MockProvider:
    """Builds MockModel instances from a ModelRef's ``settings['script']``."""

    def __init__(self, scripts: dict[str, Script] | None = None) -> None:
        self._scripts = dict(scripts or {})

    async def open(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def model(self, ref: ModelRef) -> MockModel:
        key = ref.settings.get("script")
        if not key:
            raise ModelError(
                ErrorKind.PERMANENT,
                "ModelRef.settings['script'] is required for the mock provider",
            )
        script = self._scripts.get(key)
        if script is None:
            script = _load_script_by_path(key)
        return MockModel(ref.model, script)


def provider(ref: ModelRef) -> MockProvider:
    """Provider registry entry point: ``pllmenary.testing.mock:provider``."""
    del ref
    return MockProvider()
