# Offline AI Trust model comparison

The comparison CLI evaluates the current chat model, Clef and Clef Flash on
the same audited, frozen entry inputs. It runs separately from Moonwalker and
never starts the application, submits trading work, changes configuration or
writes to the operational prediction ledger. It uses existing Python dependencies
on macOS/Linux; no model download or new service is installed.

## Inspect inputs without contacting Ollama

From the repository root, using the development virtual environment:

```bash
./.venvs/dev/bin/python scripts/compare_ai_trust.py \
  --database /absolute/path/to/moonwalker.sqlite \
  --output /tmp/moonwalker-ai-inspection
```

Supply the actual database file path. Alternatively, use `--input` with a JSONL
file in the format below. The default is an offline inspection: neither inference
nor provider metadata requests occur. `--limit` bounds the source to at most
10,000 rows (default); each JSONL row must fit within 64 KiB and selected input
must fit within 16 MiB. The SQLite reader
uses a read-only connection and one consistent transaction, without schema setup.
This limit applies before eligibility filtering; exclusions appear in the report.

Older stored observations generally **cannot qualify** because they lack
audited capture provenance. Their event time alone is insufficient: market
context may have been gathered later. The tool reports `insufficient_data`
rather than reconstructing candles or inventing timing evidence.

## Collect new inputs automatically

Enable **Control Center → AI Trust → AI Trust Cockpit enabled**. Keep warning
blocking off to collect shadow observations. No additional capture setting or
Clef model in the live configuration is needed. An Ollama chat model is optional
for capture; when configured, background shadow scoring still makes only the
existing chat assessment.

For new base orders, Moonwalker freezes the order intent and currently available
market context before order submission. It includes only candles whose open
timestamp plus the configured bot timeframe ends before capture starts; invalid
timestamps or unsupported timeframes omit those candles. The snapshot and its
hash-bound provenance are saved in the existing prediction ledger after a
successful fill, before background inference is queued. The feature event time
is the capture attempt time, not the later fill timestamp. `latest_information_at`
records when the final inputs were observed locally, not candle open time.

Capture metadata is excluded from model prompts. Shadow scoring uses the frozen
snapshot, preserves any outcome attributed while inference was waiting, and
never blocks a buy on an AI warning. Existing enforced entries also retain
pre-entry provenance. Safety orders, disabled AI Trust, failed fills and legacy
post-fill/import observations do not create eligible new captures. No history is
backfilled. An unavailable/full background queue can leave a durable capture
unscored; it remains usable for the independent offline comparison. A ledger
write failure is logged and does not undo an already persisted buy.

After restarting Moonwalker with this code, use `--database` above to inspect
new captures. Closed outcomes accumulate through existing attribution; open
captures support feasibility checks but cannot establish decision quality.

## Audited input format

Each JSONL line is one object with `id`, `deal_id`, `features`, `provenance` and
optional `outcome`. IDs must be unique; the feature schema follows Moonwalker's
existing `build_entry_feature_bundle` and derived market context fields.
Only `entry_preflight` inputs qualify. Unknown fields, nested payloads,
non-finite metrics and outcome/credential fields inside features are rejected.

```json
{
  "id": "entry-123",
  "deal_id": "deal-123",
  "features": {
    "schema_version": "1",
    "source_event": "entry_preflight",
    "symbol": "BTC/USDC",
    "event_timestamp": "2026-01-01T12:00:00Z",
    "position": {"entry_price": 100.0, "entry_amount": 0.1}
  },
  "provenance": {
    "source": "audited_entry_capture_v1",
    "feature_sha256": "SHA256_OF_CANONICAL_FEATURES",
    "captured_at": "2026-01-01T12:00:00Z",
    "latest_information_at": "2026-01-01T11:59:00Z",
    "decision_at": "2026-01-01T12:00:01Z",
    "evidence": "Audited capture log identifier and location"
  },
  "outcome": {
    "status": "closed",
    "profit": 1.2,
    "duration_hours": 24.0,
    "so_count": 1
  }
}
```

The example is displayed across lines for readability; the actual file must
contain one compact object per line. `feature_sha256` hashes UTF-8 JSON encoded
with `sort_keys=True`, `separators=(",", ":")`, and `allow_nan=False`, containing
only `features`. Timestamps accept timezone-aware ISO 8601 or millisecond epoch
strings. Require `latest_information_at <= captured_at <= decision_at` and no
feature event timestamp after the decision. Evidence must cover every derived
input, including closed-candle availability, rather than just candle open times.

This is an audit evidence contract, not a signature or independent verification
of the producer's honesty. Use genuine records from an audited entry capture;
do not manufacture these fields for historical data. The application captures
new entries as described above. SQLite inputs carry the explicit metadata in
`feature_bundle_json.capture_provenance`; the reader removes it before inference.

Outcomes stay separate from every model request. Only complete closed outcomes
with finite profit, nonnegative duration and integer safety-order count enter
quality denominators. Open, blocked or incomplete outcomes remain unknown.

## Explicitly execute a bounded pilot

Once the models and audited inputs are available, an operator may opt in:

```bash
./.venvs/dev/bin/python scripts/compare_ai_trust.py \
  --input /absolute/path/to/audited-entries.jsonl \
  --output /tmp/moonwalker-ai-pilot \
  --baseline-model qwen3:8b \
  --clef-model clef:latest \
  --flash-model clef-flash:latest \
  --base-url http://localhost:11434 \
  --execute
```

Choose the actual baseline model explicitly. The tool checks `/api/version`
and `/api/tags` for Ollama 0.35.1+ and installed model digests before inference.
It does not install missing models, upgrade Ollama or change server settings.
System One requires compatible local scoring weights; incompatible models
remain provider failures. All risk, warning, severity and reason questions are
combined into one `/v1/systemone` request per Clef/Flash assessment.
The baseline uses the existing `/api/chat` prompt/parser without its retry wrapper.
Native Clef risk scores remain on a five-level 0–4 rubric. Confidence is answer
probability concentration, not a probability of a correct trading decision.
See the [official System One API](https://docs.ollama.com/api/systemone).

Execution limits:

- One inference request in flight; zero automatic retries.
- A 60-second total deadline per attempt, including post-response identity checks.
- By default, at most 30 inference attempts per run, including failed, timed-out and
  conservatively reserved interrupted attempts. Completed cache hits consume none.
- Explicit `--attempt-budget N` allows a larger experiment, up to 3,000 attempts.
  The budget is pinned in the manifest and cannot change on resume. Larger runs
  remain serial and can occupy Ollama for a substantial time.

The tool rechecks provider version and installed digests after successful
assessments before caching them. These read-only metadata GETs are additional
to the inference budget. Aliases must remain stable during the experiment;
this check cannot detect a model changed and restored between metadata reads.
Client timeout/cancellation does not guarantee that Ollama immediately stops
server-side work. A serial pilot can still contend with trading on the same server.
Use an appropriate quiet period or a separate provider when performing a pilot.

## Run artifacts and resume

Output must be a separate new directory outside the source file. It contains:

- `manifest.json`: dataset identity, provider/model digests, question/rubric and
  baseline-source identities, API version and fixed execution settings.
- `results.jsonl`: checksummed reservations and completed results, with input
  identity, event timestamp, model identity and attempt duration.
- `report.json`: exclusions, coverage, failures and descriptive paired metrics.
- `.lock`: a process lock preventing two writers from operating on one run.

Do not edit these artifacts. Writes use fsync; small durability/locking operations
run through a stdlib thread bridge while provider and database I/O stay native
async. An incomplete final journal line is discarded on resume; complete corrupt
records are rejected. Journal reads are capped at 128 MiB. A durable slot is reserved before dispatch so a crash cannot
reset the request budget. A pending reservation becomes `interrupted`, consumes
its slot and is not automatically retried. Successful identical-input cache hits
exclude outcomes from their identity and never count as fresh latency measurements.

To resume, repeat the same command with `--resume`. Input, models, provider and
execution settings must match the manifest. A dry inspection cannot be resumed
as an executing pilot: use a new output directory. An exhausted pilot stays
exhausted; a larger or new experiment requires a deliberate new run.

## Interpret the report

The primary bad-entry label is non-positive realized profit **or** duration
at least 72 hours **or** at least three safety orders. Each component is also
reported. All models' metrics use the same closed, successfully scored input
cohort; failures and unknown outcomes are counted separately. Rates use explicit
TP/FP/FN/TN counts; undefined rates are `null`, never artificial zero success.

The earlier 70% of capture groups forms a tuning partition, and the later portion
forms evaluation, with timestamp ties kept together. Observations sharing a deal
or identical input are grouped. Groups spanning the cutoff are omitted from
metrics and reported as temporal overlap. The CLI does not fit thresholds or
modify prompts: these partitions are descriptive. Any later manual tuning must
also verify that its outcome labels were available before evaluation decisions.

Fresh timings distinguish first-observed and repeated requests. A first request
may include loading; these labels do not claim measured cold/warm server residency.
The default pilot covers at most ten complete uncached three-model inputs and
commonly has fewer. It reports `feasibility_only` when a held-out cohort exists
and `insufficient_data` otherwise. Neither status establishes a model winner.

## Get an explicit model recommendation

For a larger frozen dataset, add `--attempt-budget 1200` to an executing command
to permit up to 400 complete uncached three-model assessments. Use a new output
directory; an existing 30-attempt pilot cannot be expanded on resume. Allow
enough budget to score the full selected dataset, especially the later evaluation
partition. Failed attempts still consume budget and are never retried automatically.

Both the terminal JSON and `report.json` include `recommendation` and a readable
`conclusion`. A clear winner produces **“Use MODEL for AI Trust assessments based
on this comparison: …”**, naming its missed bad entries and false warnings.
The report also shows each paired comparison's error-rate improvement, discordant
wins/losses and p-value, plus all models' held-out confusion matrices.

The fixed recommendation policy requires:

- At least 100 unique closed evaluation entries, including 30 bad and 30 good
  entries. Repeated deals or identical inputs cannot supply independent evidence.
- Every model successfully scores every closed evaluation entry. Failures or
  exhausted budgets block a recommendation rather than silently removing hard cases.
- One model reduces composite-label classification errors by at least five
  percentage points against **each** other model, with no increase in either
  missed bad entries or false warnings on that dataset.
- Each comparison passes a two-sided exact paired error test at `0.05 / 3`,
  correcting for the three model pairs considered.

These thresholds are a conservative project policy, not a guarantee that 100
trades are representative of future markets. Only the later evaluation partition
decides the recommendation; tuning metrics and latency cannot break an accuracy
tie. Insufficient samples, weak effects, ties and warning/miss tradeoffs produce
an explicit explanation instead of a winner. Market dependence and the chosen
composite label limit the inference: a recommendation does not prove increased
profit or authorize automatic model switching or live warning enforcement.

## Development verification

Protocol, label, resource, resume and isolation regressions live in
`backend/tests/test_ai_trust_comparison*.py`. Run them using pytest, then the
mandatory `PATH`-configured `scripts/ci.sh` described in AGENTS.md. Mocked
provider tests establish contracts; they do not establish real provider
acceptance or model quality. Live evaluations require an explicitly authorized run.
