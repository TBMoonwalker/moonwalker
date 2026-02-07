"""Tortoise ORM model exports."""

from .autopilot import Autopilot as Autopilot
from .appconfig import AppConfig as AppConfig
from .trades import Trades as Trades
from .opentrades import OpenTrades as OpenTrades
from .closedtrades import ClosedTrades as ClosedTrades
from .tickers import Tickers as Tickers
from .listings import Listings as Listings

__all__ = [
    "AppConfig",
    "Autopilot",
    "ClosedTrades",
    "Listings",
    "OpenTrades",
    "Tickers",
    "Trades",
]

if __name__ == "__main__":
    __models__ = [
        "Autopilot",
        "AppConfig",
        "Trades",
        "OpenTrades",
        "ClosedTrades",
        "Listings",
    ]
