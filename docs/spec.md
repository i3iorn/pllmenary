# pllmenary — Spec

_Last updated: 2026-09-19_

## Overview

A Python framework for running a panel of large language models that keep working on a question until they reach consensus, intended for use inside agentic workflows. A configurable "chairman" model oversees a set of "participant" models: participants answer in open broadcast rounds visible to the whole panel and may also exchange private one-on-one messages. When the panel has reached consensus, or the run ends for another reason, the chairman brings everything together into the final answer, breaking ties and resolving disagreement rather than simply tallying votes.

## Configuration

The system is initialized with a configuration object covering the following.

### Roles and models

- Chairman model: which model (provider, model name, credentials/endpoint) acts as chairman.
- Participant models: a list of models to use as panel members, with support for repeating a model multiple times (e.g. three instances of the same model as separate participants) and mixing different models and providers in one panel.
- Panel size / counts: how many participants of each configured model to include.
- Summarizer: the model that writes the running summary shown to participants in later rounds. The job is assigned to either the chairman or a separate model; if unset, the chairman writes it. The summarizer runs only at round boundaries, and only once the context threshold is reached (see Context threshold). Below the threshold, later rounds show participants the raw recent broadcast history and no summary. Once the summarizer has run, it runs at every later round boundary for the rest of the run, updating the summary with the messages since its last update (see Iteration loop).
- Personas: an optional system prompt per participant giving it a role or persona; the main way to diversify a panel that repeats one model, since otherwise instances differ only by sampling.
- Temperature per role: separate temperatures for participants, the chairman and the summarizer, on top of per-model overrides.
- Presets: named configurations for reuse, for example a fast preset with a single iteration and no peer-to-peer round.

### Loop control

- Maximum iterations: the maximum number of iterations.
- Minimum rounds (min_round): the number of rounds that must complete after broadcast round one before the chairman may end the run on consensus. Counting starts with the peer-to-peer round and continues across iterations. Defaults to 0, so the chairman can end the run right after broadcast round one. The other termination conditions are unaffected.
- Peer-to-peer round: on or off. When off, each iteration skips it, which serves fast presets and baseline comparisons.
- Pairing: the selection method that chooses which participant each participant may message in the peer-to-peer round. The caller injects it. Defaults to round robin, which cycles each participant through the other participants in a fixed order, advancing each iteration.
- Optional challenger: whether a participant is designated to argue against the emerging majority, and which one (see Consensus judgement).
- Execution mode: single-threaded (async in one thread), multithreaded or multiprocess. Defaults to multiprocess (see Execution model).
- Cancel behavior: what happens when the caller cancels. A hard stop ends the run at once without a synthesis, and the result carries what has been received. The alternative lets the chairman synthesize from what has been received. Defaults to hard stop (see Termination conditions).
- Context threshold: the fraction of a context window at which compaction starts. Defaults to 75%. For participants, it is the estimated size of the prompt a participant would receive, built from the raw recent broadcast history, measured against the smallest context window among the live participants. For the chairman, it is the estimated size of the chairman's own context measured against its window. A model's window comes from the model contract, or from a context-window setting on the model's configuration when the adapter cannot report one (see Iteration loop and Chairman behavior).

### Budgets and limits

- Overall timeout: a wall-clock limit for the run, measuring what the timeout scope covers (see Timeout scope). It does not run while the run waits for the caller, and it resets to its full value when the caller answers a question.
- Timeout behavior: a hard cutoff, or a soft timeout that lets the current round complete. Defaults to soft (see Termination conditions).
- Timeout scope: what the overall timeout measures. By default it measures the iterations, including the chairman's judgements and any summarization, and not the final synthesis. It can be configured to include the synthesis.
- Synthesis timeout: a separate wall-clock limit for the chairman's final synthesis, retries included. If it expires, the run ends as a chairman failure (see Termination conditions).
- Per-call timeout: a limit for each model call.
- Stall timeout: how long a round may make no progress before it closes with the responses received so far.
- Stall limit: how many iterations in a row a participant may stall before it is dropped for the rest of the run (see Failure handling).
- Retry limit and backoff: how often transient failures are retried, and the backoff schedule.
- Minimum panel: the minimum number of live participants.
- Max tokens per call: an output-token cap for each model call, settable per role or per model.
- Token budget: a per-run cap on total tokens. The orchestrator tracks actual cumulative usage per model as calls complete, not just the worst-case estimate used for the pre-round check (see Termination conditions: Budget).
- Cost budget: a per-run cap on cost. Each model's contract converts token usage into a cost (see Model support: Price), so usage can be costed as calls complete. A run with a cost budget needs a price from every model in it, all in one currency, and is refused before it starts otherwise.
- Rate limits: caps on concurrent calls and on requests per minute for each provider account, meaning a provider together with its credentials or endpoint, so two credentials for one provider have separate limits. The executor enforces them independently of the retry and backoff policy and shares them across all threads or processes of the run, so parallel calls never collectively exceed a limit. Time a call spends waiting for a free slot counts toward the overall timeout only, not toward the per-call timeout or the stall timeout.

### Infrastructure

- Message bus: the bus implementation (see Message bus).
- Storage: the storage the run uses for events, message text, checkpoints and usage records. It must satisfy the storage contract and has no default (see Storage).
- Run-state retention: how long message text and checkpoints are kept after the run ends. By default they are purged when the run ends (see Storage).
- Resume limit: how many times a run may be resumed before it ends as an orchestrator failure. Defaults to 3 (see Orchestrator).
- Other run parameters: logging and verbosity; the list is left open for extension.

## Model support

The system is model and provider agnostic. A small adapter per provider implements the following contract for every model that provider serves.

- Complete: takes role-tagged messages (system, user or assistant), an output-token cap, an optional temperature and a timeout, and returns the text, a finish reason and the token usage when the provider reports it.
- Describe: reports the model's context window and maximum output size, and whether it supports system messages and temperature. The context threshold and configuration validation use this.
- Estimate: counts the input tokens of a set of messages. Where an adapter has no tokenizer, the system falls back to a conservative estimate from character counts, corrected by the usage the provider reports.
- Price: converts a token usage into a cost in a stated currency, or reports that the model has no known price. The conversion to money belongs to the model contract and nowhere else, so any pricing rule the provider applies is the adapter's to encode.
- Classify errors: every failure is reported as transient, timeout or permanent, with the provider's retry-after hint when there is one. Only transient failures and timeouts are retried.
- Validate: checks credentials and model name without generating text, so a misconfigured run fails before it starts.
- Close: releases the adapter's resources.

The adapter also follows these rules:

- One call is one attempt. The adapter never retries, because the orchestrator owns retries and dropout and so keeps the degraded-panel flags deterministic.
- The adapter enforces the per-call timeout and honors cancellation without leaving a connection or process in a broken state.
- Only plain text goes in and out. Provider-side structured output, tool calls and JSON modes are not part of the contract.
- Credentials are referenced by name in configuration and never written to storage.
- An adapter can be created from configuration alone, so a worker thread or process can build its own.

## Participant identity

Peers are not anonymized. Every participant, the chairman and the summarizer see who said what: each broadcast answer and each private message carries its sender's identity, made of the model name plus an instance label so that repeated instances of one model stay distinguishable. Private messages are addressed to a participant by that identity.

## Message bus

All communication goes through a message bus: participant broadcasts, private messages, the outputs of the chairman and the summarizer, and any caller input or chairman question. Every message carries its sender's identity and is addressed to all participants, to one participant, or to the caller. The chairman reads every message regardless of addressee. Private messages are delivered only to their addressee, the chairman, and a separate summarizer if there is one. The spec fixes this contract, not the transport. The implementor decides what form the bus takes, for example in-process queues or an external broker. Every message carries a schema version tag, so the bus, the event log and any resumed run state can evolve across releases without breaking a run recorded under an older version.

## Execution model

Execution is configurable as single-threaded (async in one thread), multithreaded or multiprocess. The orchestrator (see Orchestrator) is separated from model execution, meaning issuing calls and collecting responses, behind an executor abstraction. The mode is then a configuration switch that leaves the orchestrator untouched, and it changes only how many model calls run at once and where they run.

The message bus must suit the mode. An in-process queue serves single-threaded and multithreaded runs, but a multiprocess run needs a bus that crosses process boundaries. Because multiprocess is the default mode, the default bus implementation must cross process boundaries. The spec sets no throughput or latency target: actual throughput is dictated by the chosen execution mode and the system resources and provider rate limits available at runtime, not by this design.

## Orchestrator

The loop is run by a deterministic orchestrator: ordinary code, not a model. It opens and closes rounds, applies the limits, budgets and timeouts, handles failures, and calls the chairman and the summarizer. The chairman supplies judgements, such as whether the panel has reached consensus, and the final synthesis. The orchestrator acts on them and decides nothing itself.

Given the same configuration, the same model responses and the same message order, the orchestrator takes the same steps. Answers within a round are ordered by participant, not by arrival time, so parallel execution never changes what any model sees.

A crash must not silently end an in-flight run, so a run is resumable. At every round boundary the orchestrator saves a checkpoint of its complete run state to storage (see Storage): the question; the current iteration and round; the full message history, private messages included; every judgement the chairman has made; each participant's latest answer; the running summary if one exists; whether summarization and chairman compaction have started; the count of rounds toward min_round; the participants dropped so far and each one's consecutive stall count; the pairing state; the time remaining on the overall timeout; and the cumulative token and cost usage. A run resumes from its latest checkpoint, at the last completed round boundary, and does not start over. Work in an unfinished round is discarded and repeated, and the usage of its calls still counts toward the budgets.

The orchestrator is a library and cannot restart itself. Resuming is done by the caller, or by a supervisor the caller runs outside the framework. The number of times a run may be resumed is limited (see Configuration: Resume limit). When the limit is exceeded, or the latest checkpoint cannot be read or has an unsupported version, the run ends as an orchestrator failure (see Termination conditions).

## Iteration loop

Each iteration consists of three steps, run in order:

1. Broadcast round one: every participant answers the question; all answers are shared with the whole panel.
2. Peer-to-peer round: each participant gets a chance to send a private message to one other participant, outside the main broadcast.
3. Broadcast round two: every participant gives an updated answer to the panel, informed by broadcast round one, the running summary if one exists, and its own private messages.

The chairman reads every message of every iteration, not just at the end. After an iteration completes, the orchestrator runs another full iteration unless a termination condition applies.

Broadcast round two is structured. Each participant's updated answer states what it changed and why, or that it held its position, answers the strongest objection raised against its view, and carries a stance tag (see Consensus judgement).

Only broadcast round one of the first iteration starts blind. At each later round boundary, the orchestrator estimates the size of the prompt participants would receive, built from the raw recent broadcast history, and compares it with the context threshold (see Configuration: Context threshold). Below the threshold, the round is built from that raw history, with no summarization overhead. At or above it, the summarizer compresses the history into agreed points and open disputes, and this round and every later one is built from that summary plus the most recent broadcast round rather than the full transcript. Each round's prompts use a snapshot taken when the round opens, so every participant sees the same history or summary (see Configuration: Summarizer).

In the peer-to-peer round, the configured pairing method decides which participant each participant may message (see Configuration: Pairing).

Private exchanges are private. A participant sees only the private messages it sent or received. Other participants never see them, in any later round, and the running summary never quotes or attributes their content. The chairman, which reads every message, still receives them.

## Chairman behavior

The chairman is active throughout the run rather than only at the end:

- Synthesis: produces the final answer by synthesizing the participants' answers, rather than simply picking the majority response.
- Tie-breaking: resolves disagreement or ties among participants as part of synthesis.
- Early termination: can end the run early if it infers, by its own judgement, that the panel has reached consensus, without waiting for the timeout or max-iteration limit.
- Always reading: reads every message as it passes the bus, but acts only at round boundaries. When a round closes, the orchestrator asks it whether the panel has reached consensus, and it can then end the run, subject to min_round and the first-round floor (see Termination conditions).
- Compaction: when the chairman's estimated context reaches the context threshold, the orchestrator replaces everything before the current iteration in the chairman's prompts with the chairman's own logged structured reasoning for those rounds, plus the running summary if one exists. Participants' latest answers and the current iteration stay raw, and the full text remains in storage. Once compaction starts it continues for the rest of the run.
- Outside the discussion: the chairman is not a participant. It reads every message but sends nothing into broadcasts or private exchanges. Its only outputs are its logged reasoning and the final result, plus the running summary when it holds the summarizer role.

## Consensus judgement

Consensus stays the chairman's judgement, with these supports around it:

- Definition: consensus means participants agree on a specific position, not merely that they have stopped disagreeing.
- Stance tags: each participant's updated answer in broadcast round two carries a structured stance (for example agree, revise or hold). The chairman treats it as input, never as a binding vote.
- Sycophancy guard: participants are prompted not to change position without a new argument or evidence. The chairman is instructed to discount agreement that arrives without a new argument or evidence, and to flag rubber-stamp agreement rather than count it as consensus.
- Optional challenger: a run may designate one participant to argue against the emerging majority during the peer-to-peer round. It is optional because forced disagreement can invent disputes.
- Advisory convergence checks: cheap mechanical signals, such as overlap between objections repeated across iterations, are computed and logged. They inform the chairman but never end a run on their own.
- Structured reasoning each round: the chairman records the points participants agree on, the disputes that remain, and what would change its assessment, and logs all three. What would change the chairman's assessment is never shown to participants. The running summary they see in later rounds, once the context threshold triggers one (see Configuration: Summarizer), covers only agreed points and open disputes and is written by the summarizer. When the chairman also holds the summarizer role, its reasoning and the summary come from separate calls, so the hidden assessment cannot leak into the summary.

## Termination conditions

The run ends on whichever of these comes first:

- Timeout: the overall wall-clock timeout is reached. The configured timeout behavior decides what happens next: a hard cutoff cancels in-flight calls and closes the round with the responses received, while a soft timeout, the default, lets the current round complete before the run stops. The timeout measures what the timeout scope covers: by default the iterations and any summarization, not the final synthesis, which has its own timeout. If the scope includes the synthesis, a hard cutoff cancels an unfinished synthesis, which ends the run as a chairman failure, while a soft timeout lets it finish.
- Max iterations: the configured maximum number of iterations completes.
- Consensus: the chairman judges that the panel has reached consensus, once min_round is satisfied.
- Budget: a cost or token budget would be exceeded. Before each round opens, the orchestrator estimates the worst-case usage of everything that can cost tokens: every participant call of the round, the chairman's judgement at its close, the summarizer's update if one would run, and the final synthesis that would follow the round. Each call counts at its worst case: its estimated input tokens (see Model support: Estimate) plus the maximum output tokens per call, once for every attempt the retry limit allows and once more for a repair retry (see Failure handling). Cost comes from the model's price (see Model support: Price). If the estimate would exceed what remains of the budget, the run ends without opening the round, and the synthesis that follows is one the estimate already covered. If the budget cannot cover the first round together with its synthesis, the run is refused before it starts.
- Deadlock: the chairman judges that positions did not move between iterations. The remaining dissent goes into the result. This is an early-exit optimization only: if the chairman never detects deadlock, max iterations still bounds the run, so deadlock-detection accuracy is not safety-critical.
- Cancelled: the caller cancels the run, and in-flight calls are cancelled. Under the default hard stop the run ends there, with no synthesis. If the cancel behavior is set to synthesize, the chairman produces a synthesis from what has been received.
- Panel below minimum: fewer than the configured minimum number of live participants remain.
- Chairman failure: the chairman still fails after retries, or its synthesis timeout expires, so no synthesis is possible (see Failure handling).
- Orchestrator failure: the run cannot be resumed, because the resume limit is exceeded or the latest checkpoint cannot be read or has an unsupported version (see Orchestrator).

After any of these except chairman failure and orchestrator failure, and except a cancel under the default hard stop, the chairman produces the final synthesis from what has been received, subject to the first-round floor.

First-round floor: the chairman needs at least the answers from broadcast round one of the first iteration. With a soft timeout, the floor is met whenever any participant answers. With a hard cutoff, if the timeout arrives before broadcast round one completes, the chairman synthesizes from the answers that had arrived; if none had, the run ends with a failure result and no synthesis.

## Result

The run returns a structured result rather than bare text. A field with no value when the result is created is set to null:

- Answer: the chairman's synthesis. It is null when the run failed (too little input arrived, the chairman failed, or the run could not be resumed) or was cancelled with a hard stop (see Termination conditions and Failure handling).
- Latest answers: each participant's most recent answer, attributed to the participant. When there is no synthesis, this is the main content of the result.
- Running summary: the most recent summary, if one was produced (see Configuration: Summarizer).
- Dissent: overruled minority positions, attributed to the participants who held them, so tie-breaking never erases the losing side. A participant may flag that the synthesis misrepresents its position; the flag is recorded here.
- Termination reason: consensus, deadlock, timeout, max iterations, budget, cancelled, panel below minimum, chairman failure, or orchestrator failure.
- Degraded-panel flags: which participants failed, stalled or were dropped, and when, plus any chairman or summarizer failure (see Failure handling).

## Failure handling

- Per-call timeout: each model call has its own timeout, separate from the overall timeout, so one hung model cannot consume the whole time budget.
- Stall detection: a round that makes no progress within a stall timeout closes with the responses received so far. Participants that had not answered are skipped for the rest of that iteration and take part again in the next one, and their late responses are discarded. A participant that stalls in the configured number of iterations in a row is dropped for the rest of the run, and answering in an iteration resets its count.
- Retry and dropout: transient failures (rate limits, server errors, timeouts) are retried with exponential backoff up to a limit. A participant that still fails is dropped for the rest of the run. Nothing is silently substituted; every drop appears in the degraded-panel flags of the result.
- Chairman and summarizer failures: the orchestrator retries their calls like any other. If the summarizer still fails, the orchestrator keeps the last good summary if one exists, or otherwise falls back to the raw recent broadcast history for that round, and records the failure. If the chairman still fails, the orchestrator ends the run and returns the participants' latest answers, the running summary if one exists, and a failure flag, with no synthesis.
- Minimum panel: a configurable minimum number of live participants. If fewer remain, the run ends as described under Termination conditions.
- Tolerant parsing: structured outputs, such as stance tags and the chairman's verdict, are parsed tolerantly, with one repair retry if unusable. If the repair retry also fails to produce parseable output, the orchestrator falls back to treating the raw text as an unstructured answer — no stance tag, or, for the chairman, no structured verdict — and logs a parse-failure event. A missing verdict counts as neither consensus nor deadlock, so the run continues. If the chairman's synthesis cannot be parsed, its raw text becomes the answer, and the orchestrator fills the dissent from the latest answers of participants whose stance is not agreement, attributed to them, so the losing side is still recorded. A parse failure does not by itself drop a participant from the panel; only the normal retry/dropout policy for call failures (timeouts, errors) does that. Only plain-text completion through the model contract is assumed (see Model support), so no provider-side structured-output feature is required.

## Prompt-injection resistance

Everything a participant writes is untrusted input to the other participants, to the chairman and to the summarizer, in broadcasts and private messages alike. Each message is wrapped in delimiters that contain a fresh random token generated for that message, and is framed as data, never as instructions. Delimiter-like sequences inside message content are stripped or escaped, so a message cannot close its own wrapper or open a forged one. The instructions of the chairman and the summarizer travel in the system channel. The summary is derived from that untrusted text, so wherever it is shown to participants or the chairman it is wrapped and framed as data in the same way.

## Event log

Every step is emitted as an event to an append-only log: broadcasts, private messages, the outputs of the chairman and the summarizer, failures and the termination. The log stores events, not content: each entry records the event type, sender and addressee identity, round and iteration number, timestamp, and a reference id, but not the message text itself. The log subscribes to the message bus, so it records exactly what happened and in what order, and supports audit without retaining the actual text participants and models produced. Failures and the termination are emitted by the orchestrator. Events are written through the storage contract (see Storage).

Message text lives separately, in the run state (see Storage), which the event log references by id but does not duplicate. Replaying the structural sequence of a run works from the event log alone; reconstructing or resuming a run's content requires the run state.

## Storage

All persistence goes through one storage contract. The spec names no database and sets no default storage. A run needs access to storage that satisfies this contract, and nothing else about that storage matters.

Storage holds four kinds of data:

- Events: the event log, append-only and without message text (see Event log).
- Message text: every message of the run, private messages included.
- Checkpoints: the orchestrator's complete run state, saved at every round boundary (see Orchestrator).
- Usage records: the token usage of every model call, with its cost when the model's contract prices it.

The contract requires these operations:

- Create a run, and list runs.
- Append events. The events are durable when the call returns.
- Record the usage of a call. It is durable when the call returns, and it is recorded as each call completes, not only at round boundaries, so a resumed run still counts the spend of a round it discarded.
- Commit a round boundary: store the round's messages, then the checkpoint. The checkpoint is stored last and is valid only if everything it refers to is already stored. Storage may make the whole commit atomic, but the contract needs only this order.
- Load the latest checkpoint, and read a run's messages, events and usage records.
- Purge a run's message text and checkpoints, which leaves its events and usage records.

These rules apply to every implementation:

- Anything stored after the latest valid checkpoint belongs to an unfinished round. A resumed run ignores it and records the resume as an event.
- A run has one writer. Several runs may share one storage, and the run id keeps them apart.
- Message text and checkpoints hold private messages, so they are kept only as configured. By default they are purged when the run ends (see Configuration: Run-state retention). Events and usage records hold no message text and stay.
- Credentials are never written to storage, and neither is the configuration, because it names them. A resumed run must be given the same configuration, and the framework rejects a different one.
- Every stored record carries the schema version tag (see Message bus), so a run recorded under an older version is either read correctly or refused with a clear error.

## Caller control

The caller can cancel a run in progress, which ends it as described under Termination conditions. An optional hook lets the caller interject into the discussion, or answer a clarifying question the chairman raises when it lacks information. The overall timeout does not run while the run waits for the caller, and it resets to its full value when the caller answers.
