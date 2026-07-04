# AI Trust Local Calibration Plan

Date: 2026-07-04
Status: Draft for plan-eng-review, scope reduced to read-only calibration V1
Target feature: Moonwalker AI Trust Cockpit

## Summary

Add a Moonwalker-local calibration layer on top of the existing Ollama AI Trust
prediction ledger. AI Trust already has optional live trade enforcement for raw
AI warnings. This V1 is read-only **for the new calibration layer**: the goal is
to measure whether local history can support better calibrated filtering later,
not to introduce a second learned blocking policy immediately. Moonwalker should
learn which AI risk scores, reason codes, symbols, and entry contexts actually
correlate with bad closed outcomes in this specific bot setup.

This keeps Ollama as the semantic scorer and uses Moonwalker as the deterministic
calibrator.

## Recommendation

Implement **local calibration rules** first.

Prompt memory is useful later for explanation quality, but it is less
deterministic and harder to validate. Offline model tuning should wait until
there are enough labeled deals to support out-of-sample testing without obvious
overfitting.

## Current State

Existing AI Trust flow:

```text
entry candidate/open deal
        |
        v
feature bundle
        |
        v
Ollama score
        |
        v
AiTrustPrediction ledger row
        |
        v
trade closes
        |
        v
bad-entry attribution
        |
        v
Statistics AI Trust Cockpit
```

Current limitations:

- Ollama does not learn from prior bad-entry reviews.
- Future AI requests do not receive past calibration outcomes.
- Moonwalker can measure warning quality, but does not yet use that quality to
  adjust future entry decisions.
- If warning enforcement blocks a trade, that trade never closes, so false
  warnings cannot be measured from real outcomes.

## Proposed V1

Add a local calibration layer that computes deterministic warning quality from
the existing prediction ledger.

```text
AiTrustPrediction rows
        |
        v
closed outcomes only
        |
        v
calibration aggregates
        |
        v
shadow effective risk policy
        |
        v
Statistics diagnostics
```

V1 should not train a model. It should compute conservative aggregates and
derive diagnostics for an effective warning threshold.

## Scope

### In Scope

- Add calibration aggregates from existing `AiTrustPrediction` rows.
- Track calibration by:
  - AI risk-score bucket.
  - Warning severity.
  - Reason code.
  - Symbol when enough samples exist.
  - Source event.
  - Bad-entry outcome reasons.
- Add minimum sample thresholds before any learned rule can be shown as usable.
- Add read-only calibration diagnostics to the Statistics AI Trust Cockpit.
- Add a shadow effective-risk calculation for diagnostics only.
- Keep all live entry behavior unchanged except the existing AI warning
  enforcement semantics that already exist before this plan.

### Out Of Scope

- Fine-tuning Ollama.
- Training sklearn, torch, xgboost, or custom ML models.
- Sending bad-entry history to Ollama in prompts.
- Replaying blocked trades as if they closed.
- Blocking entries from calibrated rules in V1.
- Changing DCA sizing, take profit, safety order logic, or Autopilot behavior.
- Control Center integration beyond showing the existing AI status.

## Data Model

Prefer deriving aggregates on demand first, but do not scan the full ledger on
every Statistics request. V1 should use an explicit bounded read window before
adding bucket aggregation:

- Recent prediction tables: latest `MAX_RECENT_PREDICTIONS` rows.
- Bad-entry review: latest `MAX_BAD_ENTRY_REVIEW` closed/warned rows.
- Calibration buckets: closed scored rows from a bounded lookback, default 180
  days, capped at the latest 1,000 closed scored rows.

Add a persisted table only if that bounded query cost becomes material.

Candidate read model:

```text
AiTrustCalibrationBucket
  bucket_key: str
  bucket_type: score_band | severity | reason_code | symbol_reason
  sample_count: int
  closed_count: int
  bad_entry_count: int
  warned_count: int
  warning_hit_count: int
  false_warning_count: int
  bad_entry_capture_count: int
  last_updated_at: datetime
```

Derived-only V1 fields can be returned from the analytics service without a new
table:

```json
{
  "bucket_type": "reason_code",
  "bucket_key": "strong_downtrend",
  "sample_count": 18,
  "bad_entry_rate": 44.4,
  "warning_hit_rate": 70.0,
  "false_warning_rate": 20.0,
  "confidence": "usable"
}
```

## Calibration Policy

Default policy:

- Confidence labels:
  - `cold`: fewer than 10 closed scored samples.
  - `warming`: 10 to 29 closed scored samples.
  - `usable`: at least 30 closed scored samples.
  - `confident`: at least 75 closed scored samples.
- Symbol-specific buckets require at least 20 closed scored samples before they
  can be labeled `usable`.
- Never reduce risk below the raw AI score in V1.
- Only raise effective risk when local outcomes show elevated bad-entry rate.
- Prefer global reason-code calibration before symbol-specific calibration.

Effective risk sketch:

```text
raw_risk_score
   |
   +-- score-band calibration
   +-- severity calibration
   +-- reason-code calibration
   +-- symbol calibration, only with enough samples
   |
   v
shadow_effective_risk_score = max(raw_risk_score, calibrated_floor)
```

Example rule:

```text
if reason_code=strong_downtrend has >= 10 closed samples
and bad_entry_rate >= 35%
then calibrated_floor = 75
```

This avoids rewarding under-warning. In V1 it only tells the operator where
Moonwalker would become more cautious if calibrated enforcement is enabled in a
future reviewed change.

## Entry Enforcement

Current enforcement blocks when:

- AI provider is unavailable while enforcement is active.
- AI returns `would_warn = true`.

Read-only V1 behavior:

- Keep existing provider-unavailable blocking unchanged.
- Keep raw `would_warn = true` blocking unchanged.
- If raw AI does not warn, compute `shadow_effective_risk_score` for analytics
  only.
- Never block because of calibrated risk in V1.
- Record diagnostics with:
  - raw score and raw warning.
  - shadow effective score.
  - calibration bucket(s) used.
  - calibration reason code.
  - no new blocked source event.

Future calibrated enforcement remains out of scope until the read-only
diagnostics show enough closed samples and stable lift over the raw AI warning.

## Important Bias

Blocked trades do not produce closed outcomes. Therefore:

- False warnings are measurable only when trades are allowed and later close OK.
- Enforcement can reduce future labeled samples for high-risk buckets.
- Calibration should show sample counts and confidence clearly.
- A future "shadow sample mode" may be needed to keep learning after enforcement
  becomes strict.

## UI

Extend the Statistics AI Trust Cockpit with a compact calibration section:

- Calibration confidence: cold, warming, usable, confident.
- Top risk reasons by bad-entry rate.
- Missed bad-entry clusters: cases where AI did not warn but outcome was bad.
- Effective threshold summary.
- Copy must stay observational:
  - "Moonwalker learned this pattern locally."
  - "Calibrated warning would have applied."
  - Avoid buy/sell language.

## API

Extend existing analytics payload rather than adding a broad API family.

Add under `ai_trust`:

```json
{
  "calibration": {
    "enabled": true,
    "confidence": "warming",
    "confidence_thresholds": {
      "warming": 10,
      "usable": 30,
      "confident": 75,
      "symbol_usable": 20
    },
    "shadow_effective_warning_threshold": 75,
    "buckets": [],
    "missed_bad_entry_clusters": []
  }
}
```

## Backend Implementation Plan

1. Add pure calibration helpers in `backend/service/ai_trust.py`.
2. Compute buckets from closed `AiTrustPrediction` rows.
3. Extend `build_analytics_payload()` with calibration diagnostics.
4. Add a pure helper that calculates shadow effective risk for scored rows and
   analytics payloads without changing the entry gate result.
5. Do not add calibration ledger columns in read-only V1. Return
   `shadow_effective_risk_score`, `calibration_reason`, and
   `calibration_buckets` as derived API diagnostics only.
6. Revisit persisted calibration audit fields only when a future reviewed change
   lets calibrated risk affect live entry decisions.
7. Keep provider failure behavior unchanged.

## Test Plan

Backend tests:

- Calibration buckets compute correct bad-entry rates.
- Buckets below minimum sample count are marked cold and never usable.
- Shadow calibrated risk can raise but never lower raw AI risk.
- Raw `would_warn = true` still blocks before calibration.
- Provider unavailable behavior remains unchanged.
- Calibration diagnostics never change `AiTrustEntryGate.allowed`.
- Blocked trades do not count as closed calibration samples.
- Outcome attribution still labels bad entries from profit, duration, and safety
  order count.

Frontend tests:

- Statistics renders calibration empty, warming, usable, and confident states.
- Long reason codes and symbol names do not break mobile tables.
- Copy distinguishes local calibration from model training.

CI:

- Run mandatory `cd scripts && ./ci.sh`.

## Open Questions For Eng Review

1. Should V1 persist calibration aggregates or derive them on demand?
   Recommendation: derive on demand first.

2. Should calibrated enforcement be a separate future config key?
   Recommendation: yes, but defer the key until enforcement is implemented.

3. Should calibration be allowed to block trades immediately?
   Decision from plan-eng-review scope gate: no. V1 is read-only calibration.

4. Should prompt memory be included in V1?
   Recommendation: no. Keep V1 deterministic and auditable.

5. Should blocked trades be modeled as counterfactual false warnings?
   Recommendation: no. Do not invent outcomes.

## Review Focus

Ask plan-eng-review to scrutinize:

- Whether derived-on-demand aggregates are sufficient for Moonwalker's SQLite
  single-instance model.
- Whether the sample thresholds are too low for live capital.
- Whether future calibrated blocking would create a data starvation loop.
- Whether ledger schema changes are worth the migration cost.
- Whether UI copy makes the difference between local calibration and AI model
  training clear.

## Eng Review Decisions

The plan-eng-review reduced and hardened V1:

1. The new calibration layer is read-only in V1. Existing raw AI warning
   enforcement remains live and unchanged.
2. Calibration analytics must use a bounded read window instead of scanning the
   entire AI trust ledger.
3. Confidence labels must require larger sample counts before the UI calls a
   pattern usable.
4. Calibration fields are derived in the API only. No ledger migration is
   required for read-only V1.

## NOT In Scope

- Calibrated trade blocking: defer until read-only diagnostics show enough
  closed samples and stable lift over raw AI warnings.
- Prompt memory: defer because it is less deterministic and harder to test than
  local aggregate calibration.
- Ollama fine-tuning or local ML training: defer until there are enough labeled
  deals for out-of-sample validation.
- Persisted calibration aggregate table: defer until the bounded query path is
  measured and found too slow.
- Counterfactual labels for blocked trades: do not invent outcomes for trades
  that never opened.
- DCA sizing, TP, safety order, and Autopilot changes: unrelated to read-only
  calibration diagnostics.

## What Already Exists

- `backend/service/ai_trust.py` already builds privacy-minimized feature
  bundles, calls Ollama, validates output, records ledger rows, attributes
  closed outcomes, and builds the AI Trust Statistics payload.
- `backend/model/aitrustprediction.py` already stores raw score, warning,
  reason codes, feature snapshots, provider status, and closed-outcome labels.
- `backend/service/orders.py` already calls `evaluate_entry_enforcement()` for
  base-order entry checks, so calibrated V1 must not change that return path.
- `frontend/src/views/StatisticsView.vue` already renders the AI Trust Cockpit,
  recent predictions, and bad-entry review tables.
- `frontend/src/stores/analytics.ts` already owns the typed analytics payload
  contract for `ai_trust`.

## Data Flow

```text
Closed AiTrustPrediction rows
        |
        | bounded by lookback/cap
        v
Calibration helper
        |
        +--> score-band buckets
        +--> severity buckets
        +--> reason-code buckets
        +--> symbol buckets, only if sample count is high enough
        |
        v
Shadow effective risk diagnostics
        |
        v
/analytics/overview ai_trust.calibration
        |
        v
Statistics AI Trust Cockpit
```

Implementation files that should get inline comments only if the logic becomes
non-obvious:

- `backend/service/ai_trust.py`: add a short ASCII pipeline comment above the
  calibration helper if bucket construction spans multiple passes.
- `frontend/src/views/StatisticsView.vue`: no inline diagram needed if the UI
  remains metric cards plus compact tables.

## Failure Modes

| Codepath | Failure mode | Test required | Handling expectation |
|----------|--------------|---------------|----------------------|
| Bounded calibration row load | Query returns zero rows or only blocked/open rows | Yes | Return `confidence: cold`, empty buckets, and no UI error |
| Reason-code bucket parsing | Old row contains malformed `reason_codes_json` | Yes | Skip malformed reasons through existing safe parser behavior |
| Shadow effective risk | Bucket floor would be below raw score | Yes | Keep `max(raw_risk_score, calibrated_floor)` |
| Symbol-specific bucket | Symbol has too few samples | Yes | Mark cold/warming and do not label usable |
| Analytics payload | Calibration helper raises unexpectedly | Yes | Statistics should still return base AI Trust payload or clear error state |
| Frontend rendering | Long symbols/reason codes overflow mobile table | Yes | Table remains horizontally scrollable and readable |
| Operator copy | UI implies the model trained itself or tells user to trade | Yes | Copy uses observation language only |

No critical silent failure remains after the reduced scope because calibration
cannot change `AiTrustEntryGate.allowed` in V1.

## Test Coverage Diagram

```text
CODE PATHS                                             USER FLOWS
[+] backend/service/ai_trust.py                        [+] Statistics -> AI Trust Cockpit
  ├── [GAP] build bounded calibration rows                ├── [GAP] empty/cold calibration state
  ├── [GAP] bucket by score/severity/reason/symbol        ├── [GAP] warming/usable/confident labels
  ├── [GAP] malformed reason JSON skip                    ├── [GAP] missed bad-entry clusters render
  ├── [GAP] shadow effective risk max(raw,floor)          └── [GAP] mobile long symbol/reason wrapping
  └── [GAP] no change to AiTrustEntryGate.allowed

[+] frontend/src/stores/analytics.ts
  └── [GAP] typed ai_trust.calibration contract

[+] frontend/src/views/StatisticsView.vue
  ├── [GAP] calibration cards render cold/warming/usable/confident
  └── [GAP] copy says observed/would-have-warned, not buy/sell

COVERAGE: 0/12 new paths tested before implementation
QUALITY: all planned tests must be behavior + edge/error path coverage
```

## Worktree Parallelization Strategy

Sequential implementation, no parallelization opportunity. The reduced V1
mostly touches one backend service, one analytics contract, and one Statistics
view, so parallel worktrees would create more merge coordination than speed.

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific
finding above. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~1h / CC: ~20min)** — Backend calibration — Add bounded read-only calibration helpers
  - Surfaced by: Architecture Review — unbounded `AiTrustPrediction.all()` must not become the calibration query shape.
  - Files: `backend/service/ai_trust.py`, `backend/tests/test_ai_trust.py`
  - Verify: `cd scripts && ./ci.sh`
- [ ] **T2 (P2, human: ~45min / CC: ~15min)** — Calibration confidence — Implement cold/warming/usable/confident thresholds
  - Surfaced by: Architecture Review — low sample counts can make noisy patterns look meaningful.
  - Files: `backend/service/ai_trust.py`, `backend/tests/test_ai_trust.py`
  - Verify: `cd scripts && ./ci.sh`
- [ ] **T3 (P2, human: ~45min / CC: ~15min)** — Analytics contract — Return derived calibration diagnostics without ledger migration
  - Surfaced by: Code Quality Review — read-only V1 should avoid persisted calibration snapshots.
  - Files: `backend/service/ai_trust.py`, `frontend/src/stores/analytics.ts`
  - Verify: `cd scripts && ./ci.sh`
- [ ] **T4 (P2, human: ~1h / CC: ~25min)** — Statistics UI — Add compact calibration diagnostics
  - Surfaced by: Test Review — operator must see confidence, top risky reasons, missed clusters, and shadow threshold copy.
  - Files: `frontend/src/views/StatisticsView.vue`, `frontend/tests/`
  - Verify: `cd scripts && ./ci.sh`

## Completion Summary

- Step 0: Scope Challenge — scope reduced per recommendation.
- Architecture Review: 2 issues found and folded into the plan.
- Code Quality Review: 1 issue found and folded into the plan.
- Test Review: diagram produced, 12 gaps identified.
- Performance Review: 1 issue found and folded into the plan.
- NOT in scope: written.
- What already exists: written.
- TODOS.md updates: 0 items proposed.
- Failure modes: 0 critical gaps after reduction.
- Outside voice: skipped.
- Parallelization: sequential implementation, no parallelization opportunity.
- Lake Score: 4/4 recommendations chose complete or safer option.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | optional for this reduced implementation |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | outside voice skipped |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 issues folded, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run | recommended before implementation if UI polish expands |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | not needed |

- **VERDICT:** ENG CLEARED for the reduced read-only calibration V1.
NO UNRESOLVED DECISIONS
