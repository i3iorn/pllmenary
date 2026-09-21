from __future__ import annotations

import pytest

from pllmenary.config import ModelRef
from pllmenary.messages import Role
from pllmenary.models import ErrorKind, FinishReason, ModelError, PromptMessage
from pllmenary.testing.mock import (
    FailStep,
    HangStep,
    ModelRates,
    MockProvider,
    ReplyStep,
    Script,
    ScriptRule,
    provider,
)

QUESTION = PromptMessage(role=Role.USER, content="What is 2 + 2?")


def _script() -> Script:
    return Script(
        rules=[
            ScriptRule(model="alpha", pattern=r"2 \+ 2", step=ReplyStep(text="4")),
            ScriptRule(
                model="flaky",
                limit=1,
                step=FailStep(error_kind=ErrorKind.TRANSIENT),
            ),
            ScriptRule(model="flaky", step=ReplyStep(text="recovered")),
        ],
        default=ReplyStep(text="I don't know"),
        rates={"alpha": ModelRates(input_per_token=0.001, output_per_token=0.002)},
    )


async def _converse(ref: ModelRef) -> list[str]:
    mock = MockProvider(scripts={"convo": _script()})
    model = mock.model(ref)
    transcript = []
    for _ in range(3):
        result = await model.complete([QUESTION], max_output_tokens=64)
        transcript.append(result.text)
    return transcript


@pytest.mark.asyncio
async def test_scripted_conversation_replays_identically() -> None:
    ref = ModelRef(provider="mock", model="alpha", settings={"script": "convo"})
    first = await _converse(ref)
    second = await _converse(ref)
    assert first == second == ["4", "4", "4"]


@pytest.mark.asyncio
async def test_unmatched_model_falls_back_to_default() -> None:
    ref = ModelRef(provider="mock", model="unknown", settings={"script": "convo"})
    mock = MockProvider(scripts={"convo": _script()})
    result = await mock.model(ref).complete([QUESTION], max_output_tokens=64)
    assert result.text == "I don't know"


@pytest.mark.asyncio
async def test_no_rule_and_no_default_is_permanent_error() -> None:
    script = Script(rules=[], default=None)
    ref = ModelRef(provider="mock", model="alpha", settings={"script": "empty"})
    mock = MockProvider(scripts={"empty": script})
    with pytest.raises(ModelError) as excinfo:
        await mock.model(ref).complete([QUESTION], max_output_tokens=64)
    assert excinfo.value.kind is ErrorKind.PERMANENT


@pytest.mark.asyncio
async def test_use_limit_then_falls_through_to_next_rule() -> None:
    ref = ModelRef(provider="mock", model="flaky", settings={"script": "convo"})
    mock = MockProvider(scripts={"convo": _script()})
    model = mock.model(ref)
    with pytest.raises(ModelError) as excinfo:
        await model.complete([QUESTION], max_output_tokens=64)
    assert excinfo.value.kind is ErrorKind.TRANSIENT

    result = await model.complete([QUESTION], max_output_tokens=64)
    assert result.text == "recovered"


@pytest.mark.asyncio
async def test_output_truncated_at_max_tokens_reports_length() -> None:
    script = Script(rules=[], default=ReplyStep(text="x" * 100))
    ref = ModelRef(provider="mock", model="alpha", settings={"script": "long"})
    mock = MockProvider(scripts={"long": script})
    result = await mock.model(ref).complete([QUESTION], max_output_tokens=5)
    assert result.finish_reason is FinishReason.LENGTH
    assert result.usage is not None
    assert result.usage.output_tokens == 5
    assert len(result.text) == 5 * 4


@pytest.mark.asyncio
async def test_hang_step_raises_timeout_after_sleeping() -> None:
    script = Script(rules=[], default=HangStep(seconds=0.01))
    ref = ModelRef(provider="mock", model="alpha", settings={"script": "hang"})
    mock = MockProvider(scripts={"hang": script})
    with pytest.raises(ModelError) as excinfo:
        await mock.model(ref).complete([QUESTION], max_output_tokens=64)
    assert excinfo.value.kind is ErrorKind.TIMEOUT


@pytest.mark.asyncio
async def test_price_uses_configured_rates() -> None:
    ref = ModelRef(provider="mock", model="alpha", settings={"script": "convo"})
    mock = MockProvider(scripts={"convo": _script()})
    model = mock.model(ref)
    result = await model.complete([QUESTION], max_output_tokens=64)
    assert result.usage is not None
    cost = model.price(result.usage)
    assert cost is not None
    assert cost.currency == "USD"
    assert cost.amount == pytest.approx(
        result.usage.input_tokens * 0.001 + result.usage.output_tokens * 0.002
    )


@pytest.mark.asyncio
async def test_price_is_none_without_rates() -> None:
    ref = ModelRef(provider="mock", model="flaky", settings={"script": "convo"})
    mock = MockProvider(scripts={"convo": _script()})
    model = mock.model(ref)
    with pytest.raises(ModelError):
        await model.complete([QUESTION], max_output_tokens=64)
    usage_for_price_check = (await model.complete([QUESTION], max_output_tokens=64)).usage
    assert usage_for_price_check is not None
    assert model.price(usage_for_price_check) is None


def test_registry_entry_point_builds_provider() -> None:
    ref = ModelRef(provider="mock", model="alpha")
    assert isinstance(provider(ref), MockProvider)


@pytest.mark.asyncio
async def test_missing_script_selector_is_permanent_error() -> None:
    ref = ModelRef(provider="mock", model="alpha")
    mock = MockProvider(scripts={"convo": _script()})
    with pytest.raises(ModelError) as excinfo:
        mock.model(ref)
    assert excinfo.value.kind is ErrorKind.PERMANENT
