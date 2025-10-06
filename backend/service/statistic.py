import model
import helper
import pandas as pd
from service.trades import Trades
from datetime import datetime, timedelta
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/statistics.log", "statistic")


class Statistic:
    def __init__(self):
        config = helper.Config()

        self.trades = Trades()
        self.dynamic_dca = config.get("dynamic_dca", False)

    async def get_profits_overall(self, timestamp: None, period="daily"):
        profit_data = {}
        date = datetime.now()
        if timestamp:
            date = datetime.fromtimestamp(int(timestamp))
        match period:
            case "daily":
                begin_datetime = (date.replace(day=1)).date()
            case "monthly":
                begin_datetime = (date.replace(month=1)).date()
            case "yearly":
                begin_datetime = (date.replace(year=1)).date()
            case _:
                return None
        try:
            data = await model.ClosedTrades.filter(
                close_date__gt=begin_datetime
            ).values_list("close_date", "profit")

            for timestamp, profit_unit in data:
                date = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).date()
                if str(date) not in profit_data:
                    profit_data[str(date)] = profit_unit
                else:
                    profit_data[str(date)] += profit_unit

            # Resample data
            s = pd.Series(profit_data)
            s.index = pd.to_datetime(s.index)

            match period:
                case "monthly":
                    result = s.resample("ME").sum().reset_index()
                    result.columns = ["Month", "Sum"]
                    profit_data = dict(
                        zip(result["Month"].dt.strftime("%Y-%m"), result["Sum"])
                    )
                case "yearly":
                    result = s.resample("YE").sum().reset_index()
                    result.columns = ["Year", "Sum"]
                    profit_data = dict(
                        zip(result["Year"].dt.strftime("%Y"), result["Sum"])
                    )

        except Exception as e:
            logging.error(f"Error getting profits for {period} data: {e}")

        return profit_data

    async def get_profit(self):
        profit_data = {}

        # uPNL
        profit_data["upnl"] = 0
        try:
            upnl = await model.OpenTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            if upnl[0]:
                profit_data["upnl"] = upnl[0]
        except Exception as e:
            logging.error(f"Error getting losses: {e}")

        # Profit overall
        profit_data["profit_overall"] = 0
        try:
            profit = await model.ClosedTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            if profit[0] and profit_data["upnl"] != 0:
                profit_data["profit_overall"] = profit[0] + profit_data["upnl"]
            else:
                profit_data["profit_overall"] = profit[0]

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

        # Autopilot mode
        profit_data["autopilot"] = "none"
        try:
            autopilot = await model.Autopilot.all().order_by("-id").first()
            profit_data["autopilot"] = autopilot.mode if autopilot else "none"
        except Exception as e:
            logging.error(f"Error getting autopilot mode: {e}")

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
