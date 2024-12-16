from logger import LoggerFactory
from models import Trades, OpenTrades


class Data:
    def __init__(self, loglevel):

        # Class Attributes
        Data.logging = LoggerFactory.get_logger(
            "logs/data.log", "data", log_level=loglevel
        )
        Data.logging.info("Initialized")

    async def get_trades(self, symbol):
        trade_data = []
        total_cost = 0
        total_amount = 0
        current_price = 0
        safetyorders = []

        try:
            trades = await Trades.filter(symbol=symbol).values()
            opentrades = await OpenTrades.filter(symbol=symbol).values()
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
                    safetyorders + safetyorder

            trade_data = {
                "fee": trades[-1]["fee"],
                "total_cost": total_cost,
                "total_amount": total_amount,
                "symbol": trades[-1]["symbol"],
                "direction": trades[-1]["direction"],
                "side": trades[-1]["side"],
                "bot": trades[-1]["bot"],
                "current_price": current_price,
                "safetyorders": safetyorders,
            }

            return trade_data
        except Exception as e:
            Data.logging.debug(f"No trade for symbol {symbol} - Cause: {e}")
            return None

    async def get_symbols(self):
        data = await Trades.all().distinct().values_list("symbol", flat=True)
        return data

    def split_symbol(self, pair, currency):
        symbol = pair
        if not "/" in pair:
            pair, market = pair.split(currency)
            symbol = f"{pair}/{currency}"
        return symbol

    def calculate_actual_pnl(self, trades, current_price=None):
        if not current_price:
            current_price = trades["current_price"]
        total_cost = trades["total_cost"] + trades["fee"]
        average_buy_price = total_cost / trades["total_amount"]
        actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

        return actual_pnl
