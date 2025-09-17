import helper
import math


class Utils:
    def __init__(self):
        config = helper.Config()
        self.dry_run = config.get("dry_run", True)
        self.timeframe = config.get("timeframe", "1m")

    def calculate_actual_pnl(self, trades, current_price=None):
        if not current_price:
            current_price = trades["current_price"]
        total_cost = trades["total_cost"] + trades["fee"]
        average_buy_price = total_cost / trades["total_amount"]
        actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

        return actual_pnl

    def split_symbol(self, pair, currency):
        symbol = pair
        if not "/" in pair:
            pair, market = pair.split(currency)
            symbol = f"{pair}/{currency}"
        return symbol

    def convert_symbols(self, symbols):
        symbol_list = []
        for symbol in symbols:
            symbol_list.append([symbol, self.timeframe])
        return symbol_list

    def convert_numbers(self, number):
        millnames = ["", "k", "M", "B", " T"]
        n = float(number)
        millidx = max(
            0,
            min(
                len(millnames) - 1,
                int(math.floor(0 if n == 0 else math.log10(abs(n)) / 3)),
            ),
        )

        return "{:.00f} {}".format(n / 10 ** (3 * millidx), millnames[millidx])
