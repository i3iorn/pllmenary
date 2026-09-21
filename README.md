# pllmenary

A Python framework for running a panel of large language models that keep
working on a question until they reach consensus, intended for use inside
agentic workflows. A configurable "chairman" model oversees a set of
"participant" models: participants answer in open broadcast rounds visible
to the whole panel and may also exchange private one-on-one messages. When
the panel reaches consensus, or the run ends for another reason, the
chairman synthesizes a final answer, breaking ties and resolving
disagreement rather than simply tallying votes.

The full design lives in [`docs/spec.md`](docs/spec.md) and
[`docs/implementation-plan.md`](docs/implementation-plan.md). This
repository currently implements **Phase 0 (Skeleton)** of the plan:

- `pllmenary.config` — the typed, validated configuration object.
- `pllmenary.messages` — the versioned message schema, sender identity and
  addressing.
- `pllmenary.models` — the `Provider`/`Model` protocols and shared data
  types (`Model support` in the spec).
- `pllmenary.testing.mock` — the mock provider: a scripted, network-free
  implementation of the model protocols used by the test suite.

## Development

```bash
pip install -e ".[dev]"
pytest
```
