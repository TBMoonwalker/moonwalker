"""General utility helpers used across backend services."""

import math
from typing import Any


class Utils:
    """Utility class for common helper functions."""

    def calculate_actual_pnl(
        self, trades: dict[str, Any], current_price: float | None = None
    ) -> float:
        """Calculate the actual profit and loss percentage for trades.

        Args:
            trades: Dictionary containing trade data with keys: current_price, total_cost, fee, total_amount
            current_price: Optional current price to override the price from trades dict

        Returns:
            The PNL percentage as a float
        """
        if not current_price:
            current_price = trades["current_price"]
        total_cost = trades["total_cost"] + trades["fee"]
        average_buy_price = total_cost / trades["total_amount"]
        actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

        return actual_pnl

    def convert_symbols(
        self, symbols: list[str], timeframe: str = "1m"
    ) -> list[list[str]]:
        """Convert a list of symbols to symbol-timeframe pairs.

        Args:
            symbols: List of trading pair symbols (e.g., ["BTC/USDT", "ETH/USDT"])
            timeframe: Optional timeframe string (e.g., "1m", "5m", "1h")

        Returns:
            List of [symbol, timeframe] pairs
        """
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, timeframe])
        return symbol_list

    def split_symbol(self, pair: str, currency: str | None = None) -> str:
        """Split a trading pair into base and quote currencies.

        Args:
            pair: The trading pair string (e.g., "BTC-USDT", "BTC/USDT", "BTCUSDT")
            currency: Optional quote currency to use if pair format is ambiguous

        Returns:
            Formatted symbol string with forward slash separator
        """
        symbol = pair
        if "-" in pair:
            pair, market = pair.split("-")
            symbol = f"{pair}/{market}"
        elif "/" not in pair:
            pair, market = pair.split(currency)
            symbol = f"{pair}/{currency}"

        return symbol

    def convert_numbers(self, number: str | float) -> str:
        """Convert large numbers to human-readable format with suffixes (k, M, B, T).

        Args:
            number: The number to convert as string or float

        Returns:
            Formatted string with appropriate suffix (e.g., "1.23k", "4.56M")
        """
        millnames = ["", "k", "M", "B", " T"]
        n = float(number)
        millidx = max(
            0,
            min(
                len(millnames) - 1,
                int(math.floor(0 if n == 0 else math.log10(abs(n)) / 3)),
            ),
        )

        return "{:.00f} {}".format(n / 10 ** (3 * millidx), millnames[millidx])
