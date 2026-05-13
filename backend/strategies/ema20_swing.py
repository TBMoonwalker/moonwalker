"""EMA20 swing strategy."""

from typing import Any

import helper
import model
from service.strategy_ema20_swing_core import (
    EMA20_LOOKBACK_LENGTH,
    BaseEma20SwingStrategy,
)

logging = helper.LoggerFactory.get_logger(
    "logs/strategies.log",
    "ema20_swing",
)

EMA20_STATE_VERSION_SUFFIX = ":v2"


class Strategy(BaseEma20SwingStrategy):
    """EMA20 bullish swing wrapper."""

    state_model = model.Ema20SwingState
    state_version_suffix = EMA20_STATE_VERSION_SUFFIX
    strategy_display_name = "EMA20 swing"
    trend_key = "ema20_rising"
    price_position_key = "closed_above_ema20"

    def __init__(self, timeframe: str, btc_pulse: Any | None = None):
        super().__init__(timeframe, btc_pulse, logger=logging)

    def _ema_trend_matches(
        self,
        current_ema20_value: float,
        previous_ema20_value: float,
    ) -> bool:
        """Return whether EMA20 is rising."""
        return current_ema20_value > previous_ema20_value

    def _close_position_matches(
        self,
        close_value: float,
        ema20_value: float,
    ) -> bool:
        """Return whether the close sits above EMA20."""
        return close_value > ema20_value

    async def _load_indicator_inputs(self, symbol: str) -> tuple[dict[str, Any], Any]:
        """Load EMA20 and close-price inputs for the bullish wrapper."""
        ema = await self.indicators.calculate_ema(symbol, self.timeframe, [20])
        close = await self.indicators.get_close_price(
            symbol,
            self.timeframe,
            EMA20_LOOKBACK_LENGTH,
        )
        return ema, close
