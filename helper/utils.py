import helper


class Utils:
    def __init__(self):
        config = helper.Config()
        self.dry_run = config.get("dry_run", True)

    def calculate_actual_pnl(self, trades, current_price=None):
        if not current_price:
            current_price = trades["current_price"]
        if self.dry_run:
            buy_prices = []
            buy_prices.append(trades["bo_price"])
            if trades["safetyorders_count"] >= 1:
                for trade in trades["safetyorders"]:
                    buy_prices.append(trade["price"])
            if buy_prices:
                average_buy_price = sum(buy_prices) / len(buy_prices)
        else:
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
