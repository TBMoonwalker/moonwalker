"""Tortoise ORM model exports."""

from .appconfig import AppConfig as AppConfig
from .autopilot import Autopilot as Autopilot
from .closedtrades import ClosedTrades as ClosedTrades
from .listings import Listings as Listings
from .opentrades import OpenTrades as OpenTrades
from .tickers import Tickers as Tickers
from .trades import Trades as Trades
from .upnlhistory import UpnlHistory as UpnlHistory

__all__ = [
    "AppConfig",
    "Autopilot",
    "ClosedTrades",
    "Listings",
    "OpenTrades",
    "Tickers",
    "Trades",
    "UpnlHistory",
]

if __name__ == "__main__":
    __models__ = [
        "Autopilot",
        "AppConfig",
        "Trades",
        "OpenTrades",
        "ClosedTrades",
        "Listings",
        "UpnlHistory",
    ]
