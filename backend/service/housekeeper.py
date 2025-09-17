import model
import helper
import asyncio
from service.trades import Trades
from service.data import Data
from datetime import datetime, timedelta

logging = helper.LoggerFactory.get_logger("logs/housekeeper.log", "housekeeper")


class Housekeeper:
    def __init__(self):
        config = helper.Config()
        self.housekeeping_interval = config.get("housekeeping_interval", 48)

        # Class variables
        Housekeeper.status = True

    async def cleanup_ticker_database(self):
        while Housekeeper.status:
            actual_timestamp = datetime.now()
            cleanup_timestamp = actual_timestamp - timedelta(
                hours=self.housekeeping_interval
            )
            try:
                active_symbols = await Trades().get_symbols()
                ticker_symbols = await Data().get_ticker_symbol_list()
                # Do not housekeep active trades
                for symbol in ticker_symbols:
                    if symbol not in active_symbols:
                        query = await model.Tickers.filter(
                            timestamp__lt=cleanup_timestamp.timestamp()
                        ).delete()
                        logging.info(
                            f"Start housekeeping. Delete {query} entries older then {cleanup_timestamp}"
                        )
            except Exception as e:
                logging.error(f"Error db housekeeping: {e}")

            await asyncio.sleep(self.housekeeping_interval * 60)

    async def shutdown(self):
        Housekeeper.status = False
