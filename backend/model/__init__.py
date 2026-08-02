"""Tortoise ORM model exports."""

from .aitrustanalyticsrevision import (
    AiTrustAnalyticsRevision as AiTrustAnalyticsRevision,
)
from .aitrustprediction import AiTrustPrediction as AiTrustPrediction
from .appconfig import AppConfig as AppConfig
from .athcache import AthCache as AthCache
from .autopilot import Autopilot as Autopilot
from .autopilotmemoryevent import AutopilotMemoryEvent as AutopilotMemoryEvent
from .autopilotmemorystate import AutopilotMemoryState as AutopilotMemoryState
from .autopilotsymbolmemory import AutopilotSymbolMemory as AutopilotSymbolMemory
from .closedtrades import ClosedTrades as ClosedTrades
from .configmigration import ConfigMigration as ConfigMigration
from .listings import Listings as Listings
from .opentrades import OpenTrades as OpenTrades
from .placementintent import PlacementIntent as PlacementIntent
from .schemamigration import SchemaMigration as SchemaMigration
from .spotcampaigns import SpotCampaigns as SpotCampaigns
from .strategybuilder import StrategyDefinition as StrategyDefinition
from .strategybuilder import StrategyGraphState as StrategyGraphState
from .strategybuilder import StrategyVersion as StrategyVersion
from .tickers import Tickers as Tickers
from .tradeexecutions import TradeExecutions as TradeExecutions
from .tradereplaycandles import TradeReplayCandles as TradeReplayCandles
from .trades import Trades as Trades
from .unsellabletrades import UnsellableTrades as UnsellableTrades
from .upnlhistory import UpnlHistory as UpnlHistory

__all__ = [
    "AppConfig",
    "AthCache",
    "AiTrustAnalyticsRevision",
    "AiTrustPrediction",
    "Autopilot",
    "AutopilotMemoryEvent",
    "AutopilotMemoryState",
    "AutopilotSymbolMemory",
    "ClosedTrades",
    "ConfigMigration",
    "Listings",
    "OpenTrades",
    "PlacementIntent",
    "SchemaMigration",
    "SpotCampaigns",
    "StrategyDefinition",
    "StrategyGraphState",
    "StrategyVersion",
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
        "AiTrustAnalyticsRevision",
        "AiTrustPrediction",
        "AutopilotMemoryEvent",
        "AutopilotMemoryState",
        "AutopilotSymbolMemory",
        "AppConfig",
        "ConfigMigration",
        "AthCache",
        "Trades",
        "OpenTrades",
        "PlacementIntent",
        "SchemaMigration",
        "SpotCampaigns",
        "StrategyDefinition",
        "StrategyGraphState",
        "StrategyVersion",
        "ClosedTrades",
        "TradeReplayCandles",
        "TradeExecutions",
        "UnsellableTrades",
        "Listings",
        "UpnlHistory",
    ]
