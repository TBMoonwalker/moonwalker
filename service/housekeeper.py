import model
import helper
import asyncio
from datetime import datetime, timedelta

logging = helper.LoggerFactory.get_logger("logs/housekeeper.log", "housekeeper")


class Housekeeper:
    def __init__(self):
        config = helper.Config()
        self.housekeeping_interval = config.get("housekeeping_interval", 10)

        # Class variables
        Housekeeper.status = True

    async def cleanup_ticker_database(self):
        while Housekeeper.status:
            actual_timestamp = datetime.now()
            cleanup_timestamp = actual_timestamp - timedelta(
                hours=self.housekeeping_interval
            )
            try:
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
