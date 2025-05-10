import model
import json
import helper
from decimal import Decimal
from asyncache import cached
from cachetools import TTLCache
from tortoise.models import Q
from tortoise.functions import Sum
from tortoise.expressions import F

logging = helper.LoggerFactory.get_logger("logs/trades.log", "trades")


class Trades:
    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    async def get_trade_by_ordertype(self, symbol, baseorder=False):
        """
        Gives back the specific trade entries for an
        open order (baseorder or safetyorder)
        """
        # Get baseorders
        if baseorder:
            try:
                trade = await model.Trades.filter(
                    Q(baseorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                logging.error(f"Error getting baseorders from database. Cause: {e}")
        # Get safetyorders
        else:
            try:
                trade = await model.Trades.filter(
                    Q(safetyorder__gt=0), Q(symbol=symbol), join_type="AND"
                ).values()
            except Exception as e:
                logging.error(f"Error getting safetyorders from database. Cause: {e}")

        return trade

    async def get_open_trades_by_symbol(self, symbol):
        try:
            open_trades = await model.OpenTrades.filter(symbol=symbol).values()
            return open_trades
        except Exception as e:
            logging.error(f"Error getting open trades from database. Cause: {e}")

    async def get_trades_by_symbol(self, symbol):
        try:
            trades = await model.Trades.filter(symbol=symbol).values()
            return trades
        except Exception as e:
            logging.error(f"Error getting trades from database. Cause: {e}")

    async def get_open_trades(self):
        """
        Gives back the open orders including all base
        and safetyorders
        """

        def decimal_serializer(obj):
            if isinstance(obj, Decimal):
                return str(obj)

        try:
            orders = await model.OpenTrades.all().values()
            for order in orders:

                baseorder = await self.get_trade_by_ordertype(
                    order["symbol"], baseorder=True
                )
                if baseorder:
                    order["baseorder"] = baseorder[0]

                safetyorders = await self.get_trade_by_ordertype(
                    order["symbol"], baseorder=False
                )
                if safetyorders:
                    order["safetyorders"] = safetyorders
            return json.dumps(orders, default=decimal_serializer)
        except Exception as e:
            logging.error(f"Error getting open orders. Cause: {e}")
            return json.dumps([{}])

    async def get_closed_trades(self, page=0):
        try:
            # TODO: hardcoded to 10 entries per page right now
            size = 10
            if page == 0:
                orders = (
                    await model.ClosedTrades.all().order_by("-id").limit(size).values()
                )
            else:
                orders = (
                    await model.ClosedTrades.all()
                    .order_by("-id")
                    .offset(page)
                    .limit(size)
                    .values()
                )
            return json.dumps(orders)
        except Exception as e:
            logging.error(f"Error getting closed orders. Cause: {e}")
            return json.dumps([{}])

    async def get_closed_trades_length(self):
        try:
            order_length = await model.ClosedTrades.all().count()
            return json.dumps(order_length)
        except Exception as e:
            logging.error(f"Error getting closed order length. Cause: {e}")
            return json.dumps([{}])

    async def create_open_trades(self, payload):
        try:
            await model.OpenTrades.create(**payload)
            logging.debug(f"Added open trade for {payload["symbol"]}.")
        except Exception as e:
            logging.error(f"Error creating open trade. Cause {e}")

    async def update_open_trades(self, payload, symbol):
        try:
            # await model.OpenTrades.update_from_dict()
            if await self.get_open_trades_by_symbol(symbol):
                await model.OpenTrades.update_or_create(
                    defaults=payload,
                    symbol=symbol,
                )
        except Exception as e:
            logging.error(f"Error updating SO count for {symbol}. Cause {e}")

    async def create_trades(self, payload):
        try:
            await model.Trades.create(**payload)
            logging.debug(f"Added trade for {payload["symbol"]}.")
        except Exception as e:
            logging.error(f"Error creating trade. Cause {e}")

    async def delete_open_trades(self, symbol):
        try:
            await model.OpenTrades.filter(symbol=symbol).delete()
            logging.debug(f"Deleted open trade for {symbol}.")
        except Exception as e:
            logging.error(f"Error deleting open trades for {symbol}. Cause {e}")

    async def delete_trades(self, symbol):
        try:
            await model.Trades.filter(symbol=symbol).delete()
            logging.debug(f"Deleted trade for {symbol}.")
        except Exception as e:
            logging.error(f"Error deleting trades for {symbol}. Cause {e}")

    async def create_closed_trades(self, payload):
        try:
            await model.ClosedTrades.create(**payload)
        except Exception as e:
            logging.error(f"Error creating closed trade. Cause {e}")

    async def get_token_amount_from_trades(self, symbol):
        try:
            result = (
                await model.Trades.filter(symbol=symbol)
                .annotate(total_amount=Sum(F("amount") + F("amount_fee")))
                .values_list("total_amount", flat=True)
            )
            return result[0]
        except Exception as e:
            logging.error(f"Error getting total amount from {symbol}. Cause {e}")
            return None

    async def get_trades_for_orders(self, symbol):
        trade_data = []
        total_cost = 0
        total_amount = 0
        current_price = 0
        safetyorders = []

        try:
            trades = await self.get_trades_by_symbol(symbol)
            opentrades = await self.get_open_trades_by_symbol(symbol)
            if opentrades:
                current_price = opentrades[0]["current_price"]

            for order in trades:
                amount = float(order["amount"])
                amount_fee = float(order["amount_fee"])
                total_cost += float(order["ordersize"])
                total_amount += amount + amount_fee

                # Safetyorder data
                if order["safetyorder"] == 1:
                    safetyorder = {
                        "price": order["price"],
                        "so_percentage": order["so_percentage"],
                        "ordersize": order["ordersize"],
                    }
                    safetyorders.append(safetyorder)

            safetyorders_count = len(safetyorders)

            trade_data = {
                "timestamp": trades[-1]["timestamp"],
                "fee": trades[-1]["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "symbol": trades[-1]["symbol"],
                "direction": trades[-1]["direction"],
                "side": trades[-1]["side"],
                "bot": trades[-1]["bot"],
                "bo_price": trades[0]["price"],
                "current_price": current_price,
                "safetyorders": safetyorders,
                "safetyorders_count": safetyorders_count,
                "ordertype": trades[0]["ordertype"],
            }

            return trade_data
        except Exception as e:
            logging.debug(f"No trade for symbol {symbol} - Cause: {e}")
            return None

    async def stop_trade(self, symbol):
        result = False
        try:
            # Remove open trade entry
            await self.delete_open_trades(symbol)
            result = True
        except Exception as e:
            logging.error(
                f"Could not remove entries in OpenTrades for {symbol}. Cause {e}. Seems to be already removed."
            )
            pass

        try:
            # Remove trades
            await self.delete_trades(symbol)
            result = True
        except Exception as e:
            logging.error(
                f"Could not remove entries in Trades for {symbol}. Cause {e}. Seems to be already removed."
            )
            pass
        return result

    async def get_symbols(self):
        data = await model.Trades.all().distinct().values_list("symbol", flat=True)
        return data
