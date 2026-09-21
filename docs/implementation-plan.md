# pllmenary Implementation Plan

_Last updated: 2026-09-21_

## Approach

The plan builds the deterministic core against a mock provider first, then adds real adapters, execution modes, durability and evaluation. It implements the spec (see [spec.md](spec.md)) at rev 293. Five principles set the build order:

- Core before models: the orchestrator, bus, executor and storage run against a mock provider, so every rule in the spec is testable without API keys.
- Contracts before implementations: the provider, bus, executor, rate limiter, pairing method and storage backends are protocols with one simple implementation each, so changing execution mode or backend never touches the orchestrator.
- Thin vertical slice first: one iteration end to end (broadcast round one, then the chairman's synthesis) before the peer-to-peer round, summaries, budgets and durability.
- Durability from the start: all run state goes through the storage protocol from phase 1, first in memory, so resume in phase 5 switches a backend on and does not retrofit the loop.
- Evaluate before tuning: the baselines run before prompts, stance tags and the challenger are tuned.

## Decision

Evaluation proposal (decision 5). The set is about 500 questions with exact or multiple-choice answers, so scoring needs no model as judge. GPQA Diamond supplies 198 of them and has expert-checked answers, but a 2026 roundup calls it close to saturation. The rest should come from sources with headroom: that roundup lists Humanity's Last Exam as having substantial headroom, and LiveBench aims to limit contamination. I have not checked the licences or formats of either.

The size matters more than the source. If two systems disagree on 20% of questions, which is my assumption, the difference between them has a standard error of about 3.2 points at 200 questions, 2.0 at 500 and 1.4 at 1,000, so 500 questions resolve differences of about 4 points. The measure is final-answer accuracy, compared between systems on the same questions with a paired bootstrap interval, reported next to cost per correct answer and wall-clock time. A panel cannot help on questions that every single model gets right or wrong, so also report a hard subset chosen from a separate pilot run, never from the final run, or the selection inflates the result.

Two baselines belong beside the four already in the Testing table: majority vote over the same panel's independent round-one answers, and one model with self-consistency at matched token spend. Debate or Vote (NeurIPS 2025 Spotlight) found that majority voting alone accounts for most of the gains attributed to multi-agent debate. A study of five debate methods on nine benchmarks found that they did not reliably beat chain-of-thought or self-consistency, even with more compute, and that mixing models helps, so a mixed panel should also be compared with a single-model panel of the same size. The loop has to beat a vote before its extra cost is justified.

## Architecture

The orchestrator drives rounds through the call runner and executor, every message crosses the bus, and the chairman, summarizer and event log read the bus. The orchestrator consumes their outputs at round boundaries and saves checkpoints, message text and usage through the storage protocol.

Module layout for the Python package, which is named pllmenary.

| Module | Responsibility | Spec sections |
| --- | --- | --- |
| config | Typed configuration object, defaults, presets, validation | Configuration |
| messages | Message schema with version tag, sender identity, addressing | Participant identity, Message bus |
| bus | Bus protocol, per-message delimiter framing, in-process and cross-process implementations | Message bus, Execution model, Prompt-injection resistance |
| models | Provider and Model protocols, request and response types, error taxonomy, provider registry | Model support |
| ratelimit | Per-account concurrency and requests-per-minute limiter, shared across threads or processes | Configuration (Budgets and limits) |
| executor | Executor protocol with async, thread and process implementations | Execution model |
| calls | Call runner: retries with backoff, per-call timeout, stall detection and stall counts | Failure handling |
| clock | Overall and synthesis timeouts, timeout scope, pause and reset around caller questions | Configuration (Budgets and limits), Caller control |
| ledger | Token and cost accounting, worst-case estimate of every call that can cost tokens, the synthesis included, with prices from the model contract | Configuration (Budgets and limits), Termination conditions |
| context | Prompt-size estimates against the smallest live participant window, summarizer trigger, chairman compaction | Configuration (Context threshold), Iteration loop, Chairman behavior |
| orchestrator | Rounds, iterations, deterministic ordering, caller questions | Orchestrator, Iteration loop |
| termination | Pure termination policy: every condition, min_round, first-round floor, cancel behavior | Termination conditions |
| roles | Participant, chairman and summarizer prompts, tolerant parsing, repair, fallback dissent | Chairman behavior, Consensus judgement, Failure handling |
| pairing | Pairing protocol and round-robin default | Configuration (Pairing) |
| eventlog | Event log subscriber: turns bus messages and orchestrator events into events for storage | Event log |
| storage | Storage protocol, in-memory and reference SQLite backends, conformance suite | Storage |
| runstate | Run state and checkpoint types, checkpointing at round boundaries, resume, resume limit | Orchestrator |
| result | Structured result with null for missing fields | Result |
| api | Start, run, resume and the run handle | Caller control, Result |
| testing | Mock provider, scripted participants, fixtures | Testing and evaluation (this tab) |
| eval | Baseline runners and comparison harness | Testing and evaluation (this tab) |

## Milestones

The build has nine phases. The spec makes multiprocess the default mode and requires resumable runs, and those land in phases 6 and 5, so a release is gated on both. The decisions table shows that only the evaluation set and measure is open, and it must be settled before phase 8.

| Phase | Deliverable | Spec sections | Exit criteria |
| --- | --- | --- | --- |
| 0. Skeleton | Package, typed configuration with validation, message schema with version tag, mock provider, CI | Configuration, Participant identity, Message bus | Configuration rejects bad values, and the mock provider replays a scripted conversation identically every run |
| 1. Vertical slice | Model contract and provider registry, async executor, in-process bus, storage protocol with an in-memory backend, broadcast round one, chairman synthesis with its own timeout, result with nulls for missing fields | Model support, Storage, Iteration loop (step 1), Result | One iteration returns a result against the mock and against one real adapter, and a run without synthesis returns nulls where values are missing |
| 2. Full loop | Peer-to-peer round with round-robin pairing, structured broadcast round two with stance tags, private-message delivery rules, per-message delimiters with the summary framed as data, context threshold with the summarizer trigger and chairman compaction, multiple iterations | Iteration loop, Configuration (Summarizer, Context threshold), Chairman behavior, Participant identity, Message bus, Prompt-injection resistance | A multi-iteration mock run shows no participant ever receives another's private messages, every participant gets the same history or summary, the summarizer runs only at or above the threshold and then at every later boundary, and compaction keeps the chairman's prompts under the threshold |
| 3. Termination | Chairman judgement at round boundaries, min_round, consensus, deadlock, max iterations, soft and hard timeout with scope, first-round floor, cancel behavior, a missing verdict continues the run | Chairman behavior, Consensus judgement, Termination conditions | Table-driven tests cover each termination condition and their interactions |
| 4. Limits and failure | Token and cost budgets whose estimate covers every call that can cost tokens and the synthesis that follows, prices from the model contract, retries, dropout, stall skipping and stall limit, minimum panel, chairman and summarizer failure, tolerant parsing with fallback dissent, rate limiter | Failure handling, Configuration (Budgets and limits) | Fault-injection tests: hung, erroring and malformed-output models all end in the specified result, and a stalled participant is skipped and then dropped at the stall limit |
| 5. Storage and resume | Event log with events only, per-call usage records, checkpoint at every round boundary, resume with the resume limit and orchestrator failure, retention purge, reference SQLite backend, storage conformance suite | Orchestrator, Event log, Storage | A run killed at every round boundary and mid-round resumes from its last checkpoint, reaches the same decisions and counts the lost round's spend. A resume past the limit ends as an orchestrator failure, and every backend passes the conformance suite |
| 6. Execution modes | Cross-process bus, thread and process executors, shared rate limiter, cooperative cancellation, timeout clock with pause and reset around caller questions | Execution model, Caller control, Configuration (Budgets and limits) | One seeded mock scenario yields the same event sequence in single-threaded, multithreaded and multiprocess modes |
| 7. Hardening | Hostile-participant tests, cancellation, caller interjection and questions, presets, optional challenger | Prompt-injection resistance, Caller control, Consensus judgement | The injection suite passes, and cancel ends in-flight calls within the per-call timeout |
| 8. Evaluation | Baseline runners, comparison harness, prompt tuning | None (see Testing and evaluation below) | A report compares the loop with the baselines on a fixed question set |

## Technology choices

Use Python 3.12 or newer, Pydantic v2 and standard-library multiprocessing under the spawn start method. Storage is a protocol, with SQLite in WAL mode as the reference backend and an in-memory backend for tests. No provider SDK is part of the core. The Python, multiprocessing and SQLite pages were opened on 2026-09-21, the Pydantic and test-library pages on 2026-09-20. The packaging tool was not researched.

| Area | Choice | Reason and caveat |
| --- | --- | --- |
| Python | 3.12 or newer, tested on 3.12 to 3.14 | The status table, last updated 2026-05-27, has 3.10 ending in 2026-10, 3.11 in 2027-10 and 3.12 in 2028-10. 3.13 and 3.14 are in bugfix status, and 3.15 is a prerelease. |
| Pydantic | v2 for configuration, message schemas, checkpoints and results | Validation from type hints and JSON schema generation. Frozen models pickle, which process mode needs. |
| multiprocessing | Explicit spawn context for process mode | Python 3.14 moved the POSIX default from fork to forkserver, earlier versions default to fork, and the docs call forking a multithreaded process problematic. Spawn behaves the same everywhere but starts slowly, and everything passed to a worker must be picklable and importable, including configuration and the injected pairing method. |
| Cancellation in process mode | Cooperative: a cancel message plus per-call timeouts, never terminate() | The docs warn that terminating a process that is using a pipe or queue can corrupt it. |
| SQLite WAL as the reference storage backend | Reference implementation of the storage protocol, plus an in-memory backend for tests | The protocol needs only ordered durable writes with the checkpoint last, so file, key-value and cloud backends can implement it. In SQLite, readers proceed while a writer appends, but there is only one writer at a time and all processes must be on the same host, so this backend does not work over a network filesystem. |
| Message bus, process mode | Broker in the parent process over multiprocessing queues, and plain in-process queues in the other modes | An external broker can implement the same bus protocol later. |
| Provider adapters | None chosen | The core depends only on the protocols below. The first real adapter is picked in phase 1. |
| Tests | pytest with pytest-asyncio and Hypothesis | Both are actively maintained. The pages I opened did not confirm their supported Python versions or Hypothesis's stateful testing support, so check both before pinning. |

## Provider and model protocols

The core knows two protocols, Provider and Model, and no vendor. They are the spec's Model support contract as signatures: Complete is Model.complete, Describe is Model.capabilities, Estimate is Model.estimate_input_tokens, Price is Model.price, Validate is Provider.open, Close is aclose, and Classify errors is ModelError.kind. Apart from the mock provider in the next section, only signatures are defined, and every body is ....

The data types cross the protocol boundary, so they are frozen Pydantic models: picklable for process mode and safe to write to the event log.

The protocols themselves:

Three implementation notes on top of the spec's rules. Any exception other than ModelError leaving complete() is treated as permanent and logged as an adapter bug. ModelRef goes into the event log, so settings holds the name of a credential variable, never the credential. Process mode builds models inside workers, so an adapter is importable by name and constructible from its ModelRef alone.

## Mock provider

The mock provider is the first real implementation of the two protocols and lands in phase 0. It replays scripted behavior with no network, so every scenario under Testing and evaluation runs without API keys. I ran the code below on Python 3.12 and 3.11 against the types above, including in spawned worker processes, and its checks passed: replies, derived and missing usage, pricing, output truncation, scripted errors, a failure that recovers, hangs, timeouts, cancellation, and script loading by import path.

How scripts work:

- A script is an ordered list of rules. Each rule names a model, optionally a regex to search for in the last message, an optional use limit, and a step: Reply, Fail or Hang. The first matching rule that is not used up wins, then the script's default, and with neither the call fails with a permanent error. A script can also set the rates its model's price uses, and with none the model has no known price.
- A reply depends only on the model name and the request, so it is identical in every execution mode. The exception is times, which counts per process, so a fail-then-succeed scenario is deterministic only in the two in-process modes.
- ModelRef.settings['script'] selects the script. It is either a key passed to MockProvider(scripts=...) for in-process tests or an import path such as tests.scenarios:STUBBORN, which is what a worker process uses. The registry entry is pllmenary.testing.mock:provider.
- Usage is derived at four characters per token, and estimate_input_tokens uses the same count, so budget tests are predictable. Output beyond max_output_tokens is cut and reported with finish reason length.
- Latency is real time through asyncio.sleep, so scenarios keep delays short. Temperature and seed are ignored.

## System protocols

Every replaceable part of the system is a protocol with the same rule as above: signatures only. The orchestrator depends on these and on nothing concrete, which lets execution mode, bus, pairing and storage backend change without touching it.

### Messages and bus

The bus assigns sequence numbers and applies the spec's delivery rules. A participant sees broadcasts plus the private messages it sent or received. The chairman and the event log see everything, and a separate summarizer sees everything but never quotes private content. Caller questions, answers and interjections are ordinary messages, so the orchestrator needs no separate caller channel.

### Executor, rate limiter and call runner

The executor runs single attempts and knows nothing about retries. The rate limiter sits in front of it, in the parent process, so every worker shares one set of limits. The call runner applies retries, per-call timeouts and stall detection, and returns results in the order of the calls it was given, which is participant order, so arrival time never reaches the orchestrator.

### Pairing, clock and ledger

### Roles

A role turns run state into a model request and the reply back into data. Roles hold the prompts and the tolerant parsers, and know nothing about calls, retries or processes.

### Termination and orchestrator

The termination policy is a pure function, so every condition and every combination is a table-driven test with no models involved.

### Storage

One protocol covers everything the framework persists, and it names no database. Events hold no message text, only a reference to it. Message text, private messages included, and the checkpoints are the run state. Usage is stored per call through record_usage, so a round that is discarded on resume still counts against the budgets. commit_boundary writes the round's messages first and the checkpoint last. A backend may make that atomic but need not, because on resume everything after the latest valid checkpoint is ignored and a resumed event is appended. Every method is async, and a blocking backend runs in a thread inside its adapter (decision 1). All backends must pass one conformance suite, which lands in phase 5 with the reference backend (decision 4).

## Public API

The caller-facing surface is asynchronous, with one synchronous wrapper for scripts. Cancel, interject and answer map onto the spec's Caller control and are published as messages on the bus. Every dependency is optional and defaults from the configuration: the multiprocess executor, the cross-process bus and round-robin pairing. A caller replaces any of them through Dependencies. Storage is the exception. It has no default, and the caller passes one to start, run, run_sync and resume, because the spec requires only that a run has storage satisfying the contract. The configuration fields are defined in the spec's Configuration section and not repeated here.

## Testing and evaluation

Most of the spec is testable without real models, so testing runs mainly against the mock provider and only the final evaluation uses live models.

| Layer | Phases | What it checks |
| --- | --- | --- |
| Scripted scenarios | 1 to 3 | The mock provider replays conversations. Table-driven tests cover each termination condition alone and combined with min_round, soft and hard timeout, timeout scope, cancel behavior and budget. Privacy tests inspect every prompt assembled for every participant, snapshot tests confirm all participants get the same history or summary, and threshold tests confirm the summarizer starts only above the configured fraction of the smallest live participant window, keeps running once started, and that chairman compaction is measured against the chairman's own window and keeps the latest answers raw. |
| Property tests | 3, 6 | Hypothesis varies message arrival order and timing, and asserts that the orchestrator's event sequence does not change, in every execution mode. |
| Fault injection | 4 | Mock models hang, raise transient and permanent errors, emit malformed stance tags or return nothing. A stalled participant is skipped and then dropped at the stall limit. A failed repair yields null stance, an unparseable verdict continues the run, and the fallback dissent is filled. Chairman and summarizer failures follow the spec. Time spent waiting for a rate-limit slot counts toward the overall timeout only. The budget estimate covers every call that can cost tokens, meaning participants, judgement, summarizer and synthesis, with retries and the repair retry, and prices come from the model contract. A run whose budget cannot cover the first round and its synthesis is refused before it starts. |
| Crash and resume | 5 | The run is killed at every round boundary and mid-round. Resume reaches the same decisions, counts the spend of the lost round, refuses a configuration whose digest differs, the retention setting purges message text, and a resume past the resume limit ends as an orchestrator failure. One conformance suite runs against every storage backend, including a crash between the message write and the checkpoint write. |
| Replay | 5 | The structural sequence replays from the event log alone. |
| Adversarial | 7 | Hostile participants forge delimiters and inject instructions aimed at the summary and the chairman, and the summary is framed as data. Stubborn and sycophantic participants exercise the herding risk in broadcast round two. |
| Baseline evaluation | 8 | A fixed question set with verifiable answers runs through the loop, a single model, parallel answers plus one synthesis, and the loop without the peer-to-peer round. I propose adding a loop whose chairman reads only the last round, because otherwise the always-reading chairman is never tested against anything. Compare accuracy, cost and wall-clock time, and compare multiprocess with single-threaded mode. |

The question set and the accuracy measure for the baseline evaluation are proposed under Decision and not yet chosen.
