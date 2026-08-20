# LLM telemetry and the `/admin/telemetry` dashboard

First-party recording of every chat turn — its steps, tokens, latency, estimated cost and which bot
spent it. Replaces the OpenLIT stack, which never received any production traffic (see "History",
below).

## What gets recorded

One blob per chat turn, written after the response has finished, in a **private `telemetry`
container**. Every `/chat` and `/chat/stream` request produces exactly one row, including the ones
that fail:

| status | when |
| --- | --- |
| `ok` | the turn completed |
| `error` | the approach raised; the exception type, message and a truncated traceback are stored |
| `aborted` | the client disconnected mid-answer (the tokens spent are still recorded) |
| `rejected` | the request was refused before any model work — bad overrides, a bot that needs login, a provisioned bot over its session quota |

The envelope is opened **immediately after the request JSON is parsed and before the chatbot gates**,
which is what makes the `rejected` rows possible. Those are the failures an operator most needs and
they all return before the approach runs.

### Steps

Per retrieval path, the turn is broken down into:

| path | steps |
| --- | --- |
| `classic` | `query_rewrite` → `embedding` (+`image_embedding`) → `search` → `answer` |
| `agentic` | `agentic_retrieve` → children `agentic.query_planning`, `agentic.search`, `agentic.answer_synthesis` → `answer` |
| `agentic-web` | as above, but the agentic service synthesized the answer, so there is **no** `answer` step |
| `wiki` | `wiki_index_read` → `wiki_navigate` ×N → `wiki_pages_load` → `answer` |
| `assessment` | `answer` only (the HYROX bot does no retrieval) |

The agentic children come from the search service's own activity records (`elapsed_ms`,
`input_tokens`, `output_tokens`). **Before this feature those were dropped entirely, so an agentic
turn reported zero LLM tokens and therefore zero cost.** They are read defensively, without importing
the beta SDK's models, and an agentic turn that sums to zero tokens logs a WARNING — that warning is
the only tripwire for a field rename in `azure-search-documents`.

The streamed `answer` step closes when the stream is **exhausted**, not at a chunk. Azure opens a
stream with a choice-less chunk carrying `prompt_filter_results`, and treating that as terminal closed
the step at time-to-first-chunk with no usage -- which, since `close_answer_step` clears the handle,
also discarded the real usage that arrived at the end. Every streamed turn then reported a short
answer with no tokens and no cost, and the generation showed as unaccounted time. The step carries
`time_to_first_token_ms` in its payload: generation and delivery interleave (each `yield` suspends
until the client takes the chunk), so they cannot be separate steps, but TTFT still separates thinking
from emitting.

Time outside the steps is reported as `request setup` (before the first step) and `response wrap-up`
(after the last), both exact rather than estimated. On healthy turns they are tens of milliseconds.

Token totals count **leaf steps only**: an agentic child's tokens are not added again at its parent.

## Storage

```
telemetry/requests/<YYYY-MM-DD>/<ts>__<chatbot>__<traceId>.json
telemetry/rollups/daily/<YYYY-MM-DD>.json
telemetry/pricing/prices.json
```

**The blob name plus its metadata carry the whole summary row**, so every chart and the whole request
table are built from one prefix listing with zero body downloads. The body holds only the forensic
detail (messages, per-step payloads, the response) and is fetched when an operator opens one request.

Three naming decisions are load-bearing:

- **The timestamp leads the filename and the chatbot does not lead a folder.** Blob listing is
  lexicographic on the full name, so a `<day>/<chatbot>/` layout would order by bot and be
  chronological only within one bot — while the dashboard's default view is "all bots, newest first".
- **The day comes from the *finalize* time, not the turn start.** `/chat/stream` sets
  `response.timeout = None`, so a turn opened at 23:58 can finish long after midnight; keying on
  finalize means a blob can never land in a day that has already been rolled up.
- **The separator is `__`,** because the segment sanitizer collapses unsafe characters to exactly one
  underscore, so a sanitized field can never contain it and the parse is exact rather than heuristic.

### Rollups

A day that has been over for at least 60 minutes is folded once into `rollups/daily/<day>.json`
(~14 KB for a 3,000-turn day) and every later query reads that instead of re-listing. The fold is a
**pure function of a closed, immutable day**, so the ten backend replicas can compute it concurrently
and write byte-identical bytes — last-writer-wins is a no-op, not a race. It happens eagerly on the
first write of a new day, so a day is materialised whether or not anyone queries it.

Latency percentiles come from fixed-edge log-spaced histograms (72 buckets, base 20 ms, ratio 1.15),
never from stored percentiles: percentiles are not mergeable, histograms are. A quantile is known to
within **one bucket width, 15%**, which the API reports as `maxRelativeError`, and is suppressed
entirely below 20 samples. Where a percentile is suppressed, the UI falls back to the
**mean** and labels it as such rather than hiding the row or substituting a different metric -- a mean
needs no minimum sample count, and a blank cell tells an operator nothing about a bot that has served
two requests.

### Ranges

Every range is an inclusive pair of UTC days. `24h`/`7d`/`30d`/`90d`/`month` count back from today;
**`all` resolves to the first day recording produced anything**, which only the store knows, so the
routes resolve it through `telemetry_effective_range` rather than a compiled constant.

A range wider than `MAX_RANGE_DAYS` (400) is clamped by moving the **start** forward, keeping the most
recent days. Clamping the other way is what broke All time: `all` used to resolve to a compiled
`2020-01-01`, `day_range` kept the first 400 days from there, and every tab queried a window ending
in February 2021 -- so the dashboard drew nothing, and each click folded a rollup for all 400
data-less days (400 such blobs were found in the live container). Routes report the **clamped** range
back in `range.from`/`range.to`, because the UI prints it and sizes its axis from it.

A day that recorded nothing is folded but **not written**: re-deriving it costs one listing of an
empty prefix, which is cheaper than reading the blob it would replace, so storing it is pure loss and
lets a wide query mint a rollup per data-less day.

### Bucket granularity

The traffic chart buckets by hour, day, week or month; `auto` picks from the span (<=2 days hourly,
<=62 daily, <=400 weekly, beyond that monthly) to keep the axis at roughly 8-60 columns. The control
for it sits on that chart rather than in the filter bar, because it changes one chart's x axis and
nothing else.

**Hourly is the one bucket a rollup cannot serve** -- a daily rollup aggregates each key across the
whole day and cannot be split back apart -- so an hourly range is always read from raw day listings,
and `summarize` lifts its raw-day budget for it. `resolve_granularity` therefore clamps an explicit
`hour` to `day` beyond `HOURLY_MAX_DAYS` (7): without it, `range=all&granularity=hour` would list up
to `MAX_RANGE_DAYS` days of raw blobs to draw an axis of ~9,600 columns. Seven days is what the one
question an hourly axis answers actually needs -- a weekday pattern takes a full week to show.

The clamp is visible rather than silent: the summary payload reports the requested and the resolved
granularity separately, and the UI greys the Hourly control out past a week and says why.
`HOURLY_MAX_DAYS` and `HOURLY_MAX_RANGE_DAYS` in `useTelemetryQuery.ts` must stay in lockstep -- the
backend clamp is the enforcement, the frontend constant only greys out the button.

### Retention

**Nothing is pruned.** Transcripts and rollups are kept indefinitely, by explicit decision. At ~2,000
turns/day that is roughly 60,000 blobs and 1.2 GB a month (about €0.03/month of storage and €0.35/month
of write transactions), growing without bound. `TELEMETRY_RETENTION_DAYS` exists as a config knob
defaulting to `0` (keep forever) so turning pruning on later is a setting rather than a code change.

**Stated scaling ceiling: ~10,000 turns/day.** Past that, move the request index to Table Storage; the
rollup and histogram layers port unchanged.

## Privacy

Turn records contain **verbatim end-user conversations** from every bot, including the ungated,
publicly embeddable ones. Therefore:

- They live in their own `telemetry` container, **never in `content`**. With
  `AZURE_USE_AUTHENTICATION=false`, `check_path_auth` returns True and `/content/<path>` serves that
  container to anyone holding a blob name. No route reads `telemetry`.
- `overrides["user"]` — the Free Bot / rak account identifier — is **dropped**, not hashed. Nothing on
  this dashboard groups by user, and a module-salted hash of a low-entropy identifier is a lookup
  table away from the identifier itself, sitting next to a transcript.
- `TELEMETRY_STORE_BODIES=false` keeps every metric, chart and cost figure while storing no message
  text at all -- including the prompt preview, which is 120 verbatim characters of the user's last
  message. It lives in blob metadata rather than the body, which once made it look like a different
  class of thing; it is not, and the request table renders an empty preview as "not stored".
- The drawer renders message bodies as **plain text, never markdown or HTML** — rendering would hide
  the very control markers (`[[CHOICES]]`, `[[SCORE]]`, `[[SPLIT]]`) an operator opens it to inspect,
  and would make stored end-user input an injection surface inside the admin tool.
- Aggregate CSV exports never contain message text. The single-request JSON download is the
  deliberate one-at-a-time exception.

## Cost

Every cost figure is **our own recorded tokens priced with a versioned EUR table**. There is no
billing integration: the dashboard reports what the chat traffic it recorded should have cost, not
an invoice. Ingestion embeddings, `prepdocs`, the refresh scripts and anything else sharing the Azure
OpenAI resource are simply not in it, which is stated on the Costs tab.

```
cost = (prompt - cached) * input + cached * cached_input + completion * output
```

Two arithmetic invariants, both pinned by tests: `completion_tokens` **already contains**
`reasoning_tokens` (adding it roughly doubles every reasoning-model turn), and `cached_tokens` bills
at the cached rate, which on this account is one tenth of input.

Prices are EUR per million tokens and resolve through three layers, later winning: compiled defaults
-> `AZURE_OPENAI_PRICE_TABLE` (JSON env) -> `telemetry/pricing/prices.json`, which the Costs tab edits
in place. The compiled numbers were measured from real billed meters on 2026-08-19; models the
account had never billed are deliberately absent rather than guessed.

An unknown model yields `null`, **never 0** — a silent zero would make a model look free. Unpriced
models surface in their own strip on the dashboard with a link to the price editor, and their requests
are excluded from the totals rather than counted as free. **Adding a model to the price table is a
manual step**: nothing derives prices automatically.

Cost is frozen at write time as integer micro-EUR and stamped with `PRICE_VERSION`, so editing a
price never rewrites history.

## History, and what the dashboard could not inherit

Verified against live Azure on 2026-08-19:

- **OpenLIT held nothing.** `OPENLIT_ENDPOINT` was `""` on the deployed backend, so the app took the
  plain `OpenAIInstrumentor` branch and never sent it a span. Every table in its ClickHouse database
  had **0 rows**, and its volumes were `EmptyDir` regardless. There was no export to write.
- **Application Insights held about an hour.** A 365-day range query returned zero rows before
  2026-08-19T16:11Z. It also carries no cost and no chatbot attribution, and truncates each custom
  dimension at ~8 KB. An importer for it was considered and deliberately skipped.
- **Azure Cost Management** was investigated as a source of billed history and a full integration was
  built, then removed on request: the dashboard now reports only what it records itself. If billed
  spend is ever wanted again, Cost Management retains about 13 months and the removal is a single
  commit to revert.

So every figure on the dashboard starts the day recording was switched on.

## Time zone

**Stored in UTC, displayed in German time.** Blob names, rollup days and every stored timestamp are
UTC; the conversion to `Europe/Berlin` happens in the browser (`DISPLAY_TIME_ZONE` in
`charts/scales.ts`), because the browser carries complete IANA data while the backend's environment
cannot resolve `Europe/Berlin` without adding a `tzdata` dependency.

Point-in-time values — request rows, the drawer, "last seen" — are exact local times. Hour buckets are
exact too, since the offset is a whole number of hours. **Day, week and month buckets remain UTC
calendar days** and are deliberately not shifted: the rollups aggregate whole UTC days, so a shifted
label would claim a boundary the data does not have. The filter bar states this.

CSV exports keep UTC (the column is named `timestamp_utc`) so a spreadsheet has an unambiguous
instant rather than a local time with no offset.

## Operating

| variable | default | effect |
| --- | --- | --- |
| `TELEMETRY_ENABLED` | `true` | master switch for recording |
| `TELEMETRY_STORE_BODIES` | `true` | off keeps every metric but stores no message text |
| `TELEMETRY_MAX_BODY_KB` | `256` | per-record body cap |
| `TELEMETRY_RETENTION_DAYS` | `0` | `0` = keep forever |
| `AZURE_OPENAI_PRICE_TABLE` | unset | JSON price override |

The `telemetry` logger is set to `APP_LOG_LEVEL`, so these surface in Container Apps logs:
unattributed turns, agentic turns that recorded zero tokens, and every swallowed write failure.

**Nothing here may ever break a chat request.** Every recorder entry point is wrapped, the write is a
background task on the app object (bound in the route handler, because the streaming response body is
iterated after the app context has been popped), and `tests/test_telemetry_chat_integration.py` pins
that a store which fails on every call still lets an answer through.
