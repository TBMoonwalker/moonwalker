# AI Trust local calibration

The Statistics AI Trust cockpit compares recorded AI assessments with outcomes
of closed deals. Local calibration groups those observations to show which
warnings and risk patterns have been useful on this Moonwalker instance.

**Calibration is read-only.** It does not train Ollama, change safety-order
sizing, or block entries. Optional enforcement of the raw AI warning is a
separate feature; see the [AI configuration settings](configuration.md).

## Read the diagnostics

Calibration uses closed, scored predictions from the last 180 days, capped at
the latest 1,000 matching rows. It groups observations by risk-score band,
severity, reason code, symbol, and source event. The cockpit includes bad-entry
rates, warning quality, and clusters of bad entries the AI did not warn about.

Confidence labels describe available sample counts, not a guarantee of accuracy:

| Label | Closed scored samples per bucket |
|---|---|
| Cold | Fewer than 10 |
| Warming | 10–29 |
| Usable | 30–74 |
| Confident | 75 or more |

Symbol buckets have an additional minimum-sample gate of 20; that gate does not
lower the general 30-sample requirement for the usable label.

A shadow effective risk score can raise the raw score when sufficiently
supported local buckets show elevated bad-entry rates. It never lowers the raw
score. The current policy uses a 35% bad-entry-rate floor and a shadow warning
threshold of 75. These are diagnostic policy constants, not new live entry
controls.

## Understand the limits

A blocked entry never produces a closed deal. Moonwalker therefore cannot
measure its actual outcome or count it as a false warning from closed-trade
evidence. Stronger enforcement can also reduce the future samples available in
high-risk buckets.

Calibration is based on observed outcomes from this installation, not
counterfactual trades or externally trained performance claims. Empty or small
samples should be read together with their confidence labels.

## Developer contract

The analytics response exposes derived calibration under
`ai_trust.calibration`; prediction diagnostics include the shadow score,
matched buckets, and calibration reason. These diagnostics are computed from
the existing prediction ledger rather than stored as a separate calibration
ledger.

The provider, analytics, and pure calibration policy have separate owners:
[ai_provider.py](../backend/service/ai_provider.py),
[ai_trust_analytics.py](../backend/service/ai_trust_analytics.py), and
[ai_trust_calibration.py](../backend/service/ai_trust_calibration.py).
The public orchestration facade remains
[ai_trust.py](../backend/service/ai_trust.py).

Any future calibrated enforcement needs a separate design and evidence review.
Prompt memory, model training, invented outcomes for blocked entries, and a
persisted aggregate table are not part of the current calibration feature.
