"""Tortoise ORM model exports."""

from .appconfig import AppConfig as AppConfig
from .athcache import AthCache as AthCache
from .autopilot import Autopilot as Autopilot
from .closedtrades import ClosedTrades as ClosedTrades
from .emaswingstate import EmaSwingState as EmaSwingState
from .listings import Listings as Listings
from .opentrades import OpenTrades as OpenTrades
from .tickers import Tickers as Tickers
from .tradeexecutions import TradeExecutions as TradeExecutions
from .tradereplaycandles import TradeReplayCandles as TradeReplayCandles
from .trades import Trades as Trades
from .unsellabletrades import UnsellableTrades as UnsellableTrades
from .upnlhistory import UpnlHistory as UpnlHistory

__all__ = [
    "AppConfig",
    "AthCache",
    "Autopilot",
    "ClosedTrades",
    "EmaSwingState",
    "Listings",
    "OpenTrades",
    "Tickers",
    "TradeReplayCandles",
    "TradeExecutions",
    "Trades",
    "UnsellableTrades",
    "UpnlHistory",
]

if __name__ == "__main__":
    __models__ = [
        "Autopilot",
        "AppConfig",
        "AthCache",
        "Trades",
        "OpenTrades",
        "ClosedTrades",
        "TradeReplayCandles",
        "TradeExecutions",
        "EmaSwingState",
        "UnsellableTrades",
        "Listings",
        "UpnlHistory",
    ]
