from datetime import datetime
import asyncio
import json
import time
from asyncache import cached
from cachetools import TTLCache
from logger import LoggerFactory
from tortoise.models import Q
from models import Trades, OpenTrades, ClosedTrades


class Statistic:
    def __init__(self, stats, loglevel, market):
        Statistic.stats = stats

        Statistic.logging = LoggerFactory.get_logger(
            "statistics.log", "statistic", log_level=loglevel
        )
        Statistic.logging.info("Initialized")

        self.market = market

    def __calculate_trade_duration(self, start_date, end_date):
        # Convert Unix timestamps to datetime objects
        date1 = datetime.utcfromtimestamp(start_date / 1000.0)
        date2 = datetime.utcfromtimestamp(end_date / 1000.0)

        # Calculate the time difference
        time_difference = date2 - date1

        # Extract days, seconds, and microseconds
        days = time_difference.days
        seconds = time_difference.seconds
        microseconds = time_difference.microseconds

        # Calculate hours, minutes, and seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return json.dumps(
            {
                "days": days,
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds,
            }
        )

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    async def __get_trade_data(self, symbol, baseorder=False):
        if baseorder:
            trade = await Trades.filter(
                Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
            ).values()
        else:
            trade = await Trades.filter(
                Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
            ).values()

        return trade

    async def __process_stats(self, stats):
        if stats["type"] == "tp_check":
            Statistic.logging.debug(f"TP complete? {stats}")
            symbol = stats["symbol"]
            profit = stats["current_price"] * stats["total_amount"]
            amount = stats["total_amount"]
            cost = stats["total_cost"]
            current_price = stats["current_price"]
            tp_price = stats["tp_price"]
            avg_price = stats["avg_price"]
            actual_pnl = stats["actual_pnl"]
            open_timestamp = 0.0
            base_order = await self.__get_trade_data(symbol, baseorder=True)
            try:
                open_timestamp = float(base_order[0]["timestamp"])
            except Exception as e:
                self.logging.debug(f"Did not found a timestamp - taking default value")
            open_date = datetime.utcfromtimestamp(open_timestamp / 1000.0)

            if stats["sell"]:
                # Sell PNL in percent
                sell_pnl = ((current_price - avg_price) / avg_price) * 100
                # if sell_pnl > 0 and stats["direction"] == "short":
                #     sell_pnl = abs(sell_pnl)

                sell_timestamp = time.mktime(datetime.now().timetuple()) * 1000
                sell_date = datetime.now()

                # Calculate trade duration
                duration_data = self.__calculate_trade_duration(
                    open_timestamp, sell_timestamp
                )

                # Get actual trade data from OpenTrades table
                open_trade = await OpenTrades.filter(symbol=symbol).values()

                # ToDo - why is it sometimes emtpy? Race condition?
                so_count = 0
                if open_trade:
                    so_count = open_trade[0]["so_count"]

                await ClosedTrades.create(
                    symbol=symbol,
                    so_count=so_count,
                    profit=profit,
                    profit_percent=sell_pnl,
                    amount=amount,
                    cost=cost,
                    tp_price=tp_price,
                    avg_price=avg_price,
                    open_date=open_date,
                    close_date=sell_date,
                    duration=duration_data,
                )

                await OpenTrades.filter(symbol=symbol).delete()

                Statistic.logging.debug(f"Profit sell: {stats}")
            else:
                await OpenTrades.update_or_create(
                    defaults={
                        "profit": profit,
                        "profit_percent": actual_pnl,
                        "amount": amount,
                        "cost": cost,
                        "current_price": current_price,
                        "tp_price": tp_price,
                        "avg_price": avg_price,
                        "open_date": open_timestamp,
                    },
                    symbol=stats["symbol"],
                )
                # Statistic.logging.debug(f"TP-Check: {stats}")
        elif stats["type"] == "dca_check":
            if stats["new_so"]:
                Statistic.logging.debug(f"SO buy: {stats}")

            await OpenTrades.update_or_create(
                defaults={
                    "so_count": stats["so_orders"],
                },
                symbol=stats["symbol"],
            )
            # Statistic.logging.debug(f"DCA-Check: {stats}")
        elif stats["type"] == "sold_check":
            values = (
                await ClosedTrades.filter(symbol=stats["symbol"])
                .order_by("-id")
                .first()
                .values_list("id", "cost")
            )

            await ClosedTrades.update_or_create(
                defaults={
                    "amount": stats["total_amount"],
                    "cost": float(stats["total_cost"]) - float(values[1]),
                    "current_price": stats["current_price"],
                    "tp_price": stats["tp_price"],
                    "avg_price": stats["avg_price"],
                },
                id=values[0],
            )

    async def open_orders(self):
        try:
            orders = await OpenTrades.all().values()
            return json.dumps(orders)
        except Exception as e:
            self.logging.error(f"Error getting trades: {e}")
            return json.dumps([{}])

    async def closed_orders(self):
        try:
            orders = await ClosedTrades.all().values()
            return json.dumps(orders)
        except Exception as e:
            self.logging.error(f"Error getting trades: {e}")
            return json.dumps([{}])

    async def safety_orders(self, pair):
        try:
            symbol, currency = pair.split("_")
            symbol = f"{symbol}/{currency}"
            safety_orders = await self.__get_trade_data(symbol, baseorder=False)
            return json.dumps(safety_orders)
        except Exception as e:
            self.logging.error(f"Error getting trades: {e}")
            return json.dumps([{}])

    async def run(self):
        while True:
            stats = await Statistic.stats.get()
            await self.__process_stats(stats)
