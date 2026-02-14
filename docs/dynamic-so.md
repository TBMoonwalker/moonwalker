# Dynamic SO ATH Parameters

Dynamic safety-order sizing uses recent ATH from exchange OHLCV data (ccxt),
not local ticker history.

- Formula inputs:
  - Current loss (`actual_pnl`)
  - Drawdown from configurable ATH window
- Formula controls:
  - `dynamic_so_loss_weight`
  - `dynamic_so_drawdown_weight`
  - `dynamic_so_exponent`
  - `dynamic_so_min_scale` / `dynamic_so_max_scale`
- Caching:
  - ATH values are cached in the `ath_cache` table and in memory.
  - Freshness is controlled by `dynamic_so_ath_cache_ttl`.

## Dynamic SO Scale Controls
- `dynamic_so_loss_weight` (Loss weight):
  - Multiplies the current loss term (`abs(actual_pnl) / 100`) in the dynamic
    scale formula.
  - Higher value increases SO size faster as deal loss grows.
  - Typical range: `0.2` to `1.0`.

- `dynamic_so_drawdown_weight` (ATH drawdown weight):
  - Multiplies the ATH drawdown term (`(ath - price) / ath`) in the dynamic
    scale formula.
  - Higher value increases SO size faster when price is further below ATH.
  - Typical range: `0.3` to `1.5`.

- `dynamic_so_exponent` (Curve exponent):
  - Applied to drawdown term as `drawdown ** exponent`.
  - `> 1.0`: emphasizes deeper drawdowns; `0 < x < 1.0`: reacts more to
    smaller drawdowns.
  - Typical range: `1.0` to `1.5`.

- `dynamic_so_min_scale` (Dynamic min scale):
  - Lower clamp for final dynamic multiplier.
  - Prevents SO size from being reduced below this multiplier.
  - Example: `0.8` means SO size cannot drop below `80%` of base computed
    size.

- `dynamic_so_max_scale` (Dynamic max scale):
  - Upper clamp for final dynamic multiplier.
  - Prevents overly large SO size increases in extreme conditions.
  - Example: `1.8` means SO size cannot exceed `180%` of base computed size.

- `dynamic_so_ath_cache_ttl` (ATH cache TTL (sec)):
  - Cache freshness in seconds for ATH values (in-memory + DB cache read
    freshness).
  - Lower value updates ATH more often but makes more exchange requests.
  - Higher value reduces exchange load but uses older ATH values longer.
  - Typical range: `30` to `300`.

## Formula Summary
Dynamic SO multiplier is computed as:
```text
scale = clamp(
  1 + (loss_weight * loss_ratio) + (drawdown_weight * drawdown_ratio^exponent),
  min_scale,
  max_scale
)
```

Where:
- `loss_ratio = abs(actual_pnl) / 100`
- `drawdown_ratio = (ath - current_price) / ath`

Example: 1 year lookback using daily candles
```json
{
  "dynamic_so_volume_enabled": {"value": true, "type": "bool"},
  "dynamic_so_ath_lookback_value": {"value": 1, "type": "int"},
  "dynamic_so_ath_lookback_unit": {"value": "year", "type": "str"},
  "dynamic_so_ath_timeframe": {"value": "1d", "type": "str"}
}
```

Example: 1 year lookback using 4h candles
```json
{
  "dynamic_so_ath_lookback_value": {"value": 1, "type": "int"},
  "dynamic_so_ath_lookback_unit": {"value": "year", "type": "str"},
  "dynamic_so_ath_timeframe": {"value": "4h", "type": "str"}
}
```
