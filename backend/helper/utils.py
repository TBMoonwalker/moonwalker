import math


class Utils:

    def calculate_actual_pnl(self, trades, current_price=None):
        if not current_price:
            current_price = trades["current_price"]
        total_cost = trades["total_cost"] + trades["fee"]
        average_buy_price = total_cost / trades["total_amount"]
        actual_pnl = ((current_price - average_buy_price) / average_buy_price) * 100

        return actual_pnl
    
    def convert_symbols(self, symbols, timeframe=None):
        symbol_list = []
        if not timeframe:
            # ToDo - how get it from the config
            timeframe = "1m"
        for symbol in symbols:
            symbol_list.append([symbol, timeframe])
        return symbol_list

    def split_symbol(self, pair, currency=None):
        symbol = pair
        if "-" in pair:
            pair, market = pair.split("-")
            symbol = f"{pair}/{market}"
        elif not "/" in pair:
            pair, market = pair.split(currency)
            symbol = f"{pair}/{currency}"

        return symbol

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
