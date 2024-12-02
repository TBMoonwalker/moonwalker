from datetime import datetime
import asyncio
import json
import time
from asyncache import cached
from cachetools import TTLCache
from logger import LoggerFactory
from tortoise.functions import Sum
from tortoise.models import Q
from models import Trades, OpenTrades, ClosedTrades


class Statistic:
    def __init__(self, stats, loglevel, market):
        Statistic.stats = stats
        Statistic.status = True

        Statistic.logging = LoggerFactory.get_logger(
            "logs/statistics.log", "statistic", log_level=loglevel
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
        # Get baseorders
        if baseorder:
            try:
                trade = await Trades.filter(
                    Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                self.logging.error(f"Error getting baseorders from database. Cause {e}")
        # Get safetyorders
        else:
            try:
                trade = await Trades.filter(
                    Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                self.logging.error(
                    f"Error getting safetyorders from database. Cause {e}"
                )

        return trade

    async def __process_stats(self, stats):
        if stats["type"] == "tp_check":
            Statistic.logging.debug(f"TP complete? {stats}")
            symbol = stats["symbol"]
            profit = (
                stats["current_price"] * stats["total_amount"] - stats["total_cost"]
            )
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
                self.logging.debug(
                    f"Did not found a timestamp - taking default value. Cause {e}"
                )

            open_date = datetime.utcfromtimestamp(open_timestamp / 1000.0)

            if stats["sell"]:
                # Sell PNL in percent
                sell_pnl = ((current_price - avg_price) / avg_price) * 100
                sell_timestamp = time.mktime(datetime.now().timetuple()) * 1000
                sell_date = datetime.now()

                # Calculate trade duration
                duration_data = self.__calculate_trade_duration(
                    open_timestamp, sell_timestamp
                )

                # Get actual trade data from OpenTrades table
                try:
                    open_trade = await OpenTrades.filter(symbol=symbol).values()
                except Exception as e:
                    self.logging.error(
                        f"Error getting open trades from database. Cause {e}"
                    )

                # ToDo - why is it sometimes emtpy? Race condition?
                so_count = 0
                if open_trade:
                    so_count = open_trade[0]["so_count"]

                try:
                    # Create closed trade entry
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

                    # Remove open trade entry
                    await OpenTrades.filter(symbol=symbol).delete()

                    Statistic.logging.debug(f"Profit sell: {stats}")
                except Exception as e:
                    self.logging.error(
                        f"Error writing closed trade database entry. Cause {e}"
                    )

            else:
                try:
                    # Update open trade statistics
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
                except Exception as e:
                    self.logging.error(
                        f"Error updating open trade database entry. Cause {e}"
                    )

        elif stats["type"] == "dca_check":
            if stats["new_so"]:
                Statistic.logging.debug(f"SO buy: {stats}")

            # Update SO count statistics
            try:
                await OpenTrades.update_or_create(
                    defaults={
                        "so_count": stats["so_orders"],
                    },
                    symbol=stats["symbol"],
                )
            except Exception as e:
                self.logging.error(
                    f"Error updating SO count for {stats["symbol"]}. Cause {e}"
                )
            Statistic.logging.debug(f"DCA-Check: {stats}")

        elif stats["type"] == "sold_check":
            try:
                values = (
                    await ClosedTrades.filter(symbol=stats["symbol"])
                    .order_by("-id")
                    .first()
                    .values_list("id", "cost")
                )
            except Exception as e:
                self.logging.error(
                    f"Error getting closed trades for {stats["symbol"]}. Cause {e}"
                )

            try:
                await ClosedTrades.update_or_create(
                    defaults={
                        "amount": stats["total_amount"],
                        "profit": float(stats["total_cost"]) - float(values[1]),
                        "current_price": stats["current_price"],
                        "tp_price": stats["tp_price"],
                        "avg_price": stats["avg_price"],
                    },
                    id=values[0],
                )
            except Exception as e:
                self.logging.error(
                    f"Error updating closed trades for {stats["symbol"]}. Cause {e}"
                )

    async def open_orders(self):
        try:
            orders = await OpenTrades.all().values()
            return json.dumps(orders)
        except Exception as e:
            self.logging.error(f"Error getting open trades: {e}")
            return json.dumps([{}])

    async def closed_orders_length(self):
        try:
            order_length = await ClosedTrades.all().count()
            return json.dumps(order_length)
        except Exception as e:
            self.logging.error(f"Error getting closed trades: {e}")
            return json.dumps([{}])

    async def closed_orders(self, page=0):
        try:
            size = 10
            if page == 0:
                orders = await ClosedTrades.all().order_by("-id").limit(size).values()
            else:
                orders = (
                    await ClosedTrades.all()
                    .order_by("-id")
                    .offset(page)
                    .limit(size)
                    .values()
                )
            return json.dumps(orders)
        except Exception as e:
            self.logging.error(f"Error getting closed trades: {e}")
            return json.dumps([{}])

    async def profit_statistics(self):
        profit_data = {}

        # uPNL
        profit_data["upnl"] = 0
        try:
            upnl = await OpenTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            profit_data["upnl"] = upnl[0]
        except Exception as e:
            self.logging.error(f"Error getting losses: {e}")

        # Profit overall
        profit_data["profit_overall"] = 0
        try:
            profit = await ClosedTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            profit_data["profit_overall"] = profit[0] - profit_data["upnl"]
        except Exception as e:
            self.logging.error(f"Error getting profit: {e}")

        # Funds locked in deals
        profit_data["funds_locked"] = 0
        try:
            funds_locked = await OpenTrades.annotate(total=Sum("cost")).values_list(
                "total", flat=True
            )
            profit_data["funds_locked"] = funds_locked[0]
        except Exception as e:
            self.logging.error(f"Error getting funds: {e}")

        # TBD - Profit per Day

        return json.dumps(profit_data)

    async def sum_profit(self):
        try:
            profit = await ClosedTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            return json.dumps(profit)
        except Exception as e:
            self.logging.error(f"Error getting closed trades: {e}")
            return json.dumps([{}])

    async def safety_orders(self, pair):
        try:
            symbol, currency = pair.split("_")
            symbol = f"{symbol}/{currency}"
            safety_orders = await self.__get_trade_data(symbol, baseorder=False)
            return json.dumps(safety_orders)
        except Exception as e:
            self.logging.error(f"Error getting safety orders: {e}")
            return json.dumps([{}])

    async def run(self):
        while Statistic.status:
            stats = await Statistic.stats.get()
            await self.__process_stats(stats)

    async def shutdown(self):
        Statistic.status = False
