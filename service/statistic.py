import model
import helper
from service.trades import Trades
from datetime import datetime, timedelta
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/statistics.log", "statistic")


class Statistic:
    def __init__(self):
        config = helper.Config()

        self.trades = Trades()
        self.dynamic_dca = config.get("dynamic_dca", False)

    async def get_profits_overall(self, timestamp: None):
        profit_data = {}
        profit_data["profit_month"] = {}
        begin_month = (datetime.now().replace(day=1)).date()
        if timestamp:
            begin_month = (datetime.fromtimestamp(int(timestamp)).replace(day=1)).date()
        try:
            profit_month = await model.ClosedTrades.filter(
                close_date__gt=begin_month
            ).values_list("close_date", "profit")
            for timestamp, profit_day in profit_month:
                date = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).date()
                if str(date) not in profit_data["profit_month"]:
                    profit_data["profit_month"][str(date)] = profit_day
                else:
                    profit_data["profit_month"][str(date)] += profit_day
        except Exception as e:
            logging.error(f"Error getting profits for the month: {e}")

        return profit_data

    async def get_profit(self):
        profit_data = {}

        # uPNL
        profit_data["upnl"] = 0
        try:
            upnl = await model.OpenTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            profit_data["upnl"] = upnl[0]
        except Exception as e:
            logging.error(f"Error getting losses: {e}")

        # Profit overall
        profit_data["profit_overall"] = 0
        try:
            profit = await model.ClosedTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            if profit[0] and profit_data["upnl"]:
                profit_data["profit_overall"] = profit[0] + profit_data["upnl"]

        except Exception as e:
            logging.error(f"Error getting profit: {e}")

        # Funds locked in deals
        profit_data["funds_locked"] = 0
        try:
            funds_locked = await model.OpenTrades.annotate(
                total=Sum("cost")
            ).values_list("total", flat=True)
            profit_data["funds_locked"] = funds_locked[0]
        except Exception as e:
            logging.error(f"Error getting funds: {e}")

        profit_data["profit_week"] = {}
        begin_week = (
            datetime.now() + timedelta(days=(0 - datetime.now().weekday()))
        ).date()
        try:
            profit_week = await model.ClosedTrades.filter(
                close_date__gt=begin_week
            ).values_list("close_date", "profit")
            for timestamp, profit_day in profit_week:
                date = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).date()
                if str(date) not in profit_data["profit_week"]:
                    profit_data["profit_week"][str(date)] = profit_day
                else:
                    profit_data["profit_week"][str(date)] += profit_day
        except Exception as e:
            logging.error(f"Error getting profits for the week: {e}")

        return profit_data

    async def update_statistic_data(self, stats):
        if stats["type"] != "dca_check":
            profit = (
                stats["current_price"] * stats["total_amount"] - stats["total_cost"]
            )
            open_timestamp = 0.0
            base_order = await self.trades.get_trade_by_ordertype(
                stats["symbol"], baseorder=True
            )

            try:
                open_timestamp = float(base_order[0]["timestamp"])
            except Exception as e:
                open_timestamp = datetime.timestamp(datetime.now())
                logging.debug(
                    f"Did not found a timestamp - taking default value. Cause {e}"
                )
        else:
            if stats["new_so"]:
                logging.debug(f"SO buy: {stats}")

            # Update SO count statistics
            payload = {"so_count": stats["so_orders"]}
            await self.trades.update_open_trades(payload, stats["symbol"])
            logging.debug(stats)

        # Comes from DCA module
        if stats["type"] == "tp_check":
            logging.debug(stats)

            # Update open trade statistics
            payload = {
                "profit": profit,
                "profit_percent": stats["actual_pnl"],
                "amount": stats["total_amount"],
                "cost": stats["total_cost"],
                "current_price": stats["current_price"],
                "tp_price": stats["tp_price"],
                "avg_price": stats["avg_price"],
                "open_date": open_timestamp,
            }
            await self.trades.update_open_trades(payload, stats["symbol"])
