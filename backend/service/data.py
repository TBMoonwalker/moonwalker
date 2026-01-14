
import helper
import model
import pandas as pd
from datetime import datetime, timedelta, timezone
from service.exchange import Exchange

logging = helper.LoggerFactory.get_logger("logs/data.log", "data")


class Data:
    def __init__(self):
        utils = helper.Utils()
        self.exchange = Exchange()
        self.utils = utils

    async def get_listing_date(self, config, symbol: str) -> datetime:
        """
        Fetch the listing date of a token, using SQLite cache with Tortoise ORM.
        """
        # Check cache first
        listing = await model.Listings.get_or_none(symbol=symbol)
        if listing:
            return listing.listing_date

        # If not cached → fetch from exchange        
        try:
            ohlcv = self.exchange.get_history_for_symbol(config, symbol, timeframe="1d")
            if not ohlcv:
                logging.error(f"No OHLCV data available for {symbol}")
            else:
                first_timestamp = ohlcv[0][0]
                listing_date = datetime.fromtimestamp(
                    first_timestamp / 1000, tz=timezone.utc
                )

                # Save to DB cache
                await model.Listings.create(symbol=symbol, listing_date=listing_date)
                return listing_date
        except Exception as e:
            logging.error(f"Error fetching OHLCV for {symbol}: {e}")

        return None

    async def is_token_old_enough(self, config, symbol: str) -> bool:
        """
        Return False if token is newer than threshold_days, True otherwise.
        """
        threshold_days = config.get("pair_age", 30)
        listing_date = await self.get_listing_date(config, symbol)
        if listing_date:
            threshold_date = datetime.now(timezone.utc) - timedelta(days=threshold_days)
            return listing_date <= threshold_date
        else:
            return False

    async def get_ticker_symbol_list(self):
        symbols = await model.Tickers.all().distinct().values_list("symbol", flat=True)
        return symbols

    def __calculate_min_candle_date(self, timerange, length):

        # Convert timerange with buffer
        match timerange:
            case "1D":
                length_minutes = 2880
            case "4h":
                length_minutes = 480
            case "60min":
                length_minutes = 120
            case "30min":
                length_minutes = 90
            case "15min":
                length_minutes = 45
            case "10min":
                length_minutes = 20
            case "5min":
                length_minutes = 10

            # If an exact match is not confirmed, this last case will be used if provided
            case _:
                length_minutes = 30

        # Input parameters
        num_candles = length  # Number of candles with buffer
        end_time = datetime.now()

        # Calculate the total look-back duration
        lookback_duration = timedelta(minutes=length_minutes * num_candles)

        # Calculate the minimum date
        min_date = end_time - lookback_duration

        return datetime.timestamp(min_date)

    async def count_history_data_for_symbol(self, symbol):
        try:
            query = await model.Tickers.filter(symbol=f"{symbol}").count()
            logging.debug(f"Counted {query} entries for symbol {symbol}")
            return query
        except Exception as e:
            logging.error(f"Error counting history data for symbol {symbol}: {e}")

        return False

    async def delete_ticker_data_for_trades(self, symbol):
        try:
            query = await model.Tickers.filter(symbol=f"{symbol}").delete()
            logging.info(f"Delete {query} entries for symbol {symbol}")
            return True
        except Exception as e:
            logging.error(f"Error deleting old ticker data for symbol {symbol}: {e}")

        return False

    async def add_history_data_for_symbol(self, symbol, history_data, config):
        if await self.delete_ticker_data_for_trades(symbol):
            try:
                if await self.__fetch_history_data_for_symbol(symbol, history_data, config):
                    logging.info(f"Added history for {symbol}")
                    return True
            except Exception as e:
                logging.error(f"Error adding history for {symbol}. Cause: {e}")

        return False

    async def __fetch_history_data_for_symbol(self, symbol, history_data, config):
        ohlcv = []
        try:
            since = int((datetime.now(timezone.utc) - timedelta(days=history_data)).timestamp() * 1000)
            ohlcv_data = self.exchange.get_history_for_symbol(
                config, symbol, config.get("strategy_timeframe", "1m"), limit=1000, since=since
            )
            
            symbol, market = symbol.split("/")

            for ticker in ohlcv_data:
                ticker = model.Tickers(
                    timestamp=ticker[0],
                    symbol=symbol + "/" + market,
                    open=ticker[1],
                    high=ticker[2],
                    low=ticker[3],
                    close=ticker[4],
                    volume=ticker[5],
                )
                ohlcv.append(ticker)

            await model.Tickers.bulk_create(ohlcv)

            return True

        except Exception as e:
            logging.error(f"Error fetching historical data from Exchange. Cause: {e}")

        return False

    async def get_ohlcv_for_pair(self, pair, timerange, timestamp_start, offset):
        # 600000 --> 60 minutes in milliseconds before
        # start_date = datetime.fromtimestamp(((float(timestamp_start) - 600000) / 1000.0),UTC,)
        symbol = self.utils.split_symbol(pair)
        start_timestamp = float(timestamp_start) - 60000
        ohlcv = {}
        query = (
            await model.Tickers.filter(symbol=symbol)
            .filter(timestamp__gt=start_timestamp)
            .values("timestamp", "open", "high", "low", "close", "volume")
        )

        if query:
            df = self.resample_data(pd.DataFrame(query), timerange)

            df["time"] = df["timestamp"].astype(int) + 60 * int(offset)
            df.drop_duplicates(subset=["time"], inplace=True)
            df.rename(
                columns={
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                },
                inplace=True,
            )
            df.drop("volume", axis=1, inplace=True)
            df.drop("timestamp", axis=1, inplace=True)
            ohlcv = df.to_json(orient="records")

        return ohlcv

    async def get_data_for_pair(self, pair, timerange, length):
        try:
            symbol = self.utils.split_symbol(pair)
            start_date = self.__calculate_min_candle_date(timerange, length)
            query = (
                await model.Tickers.filter(symbol=symbol)
                .filter(timestamp__gt=start_date)
                .values()
            )
        except Exception as e:
            raise(e)

        if query:
            df = pd.DataFrame(query)
            df.dropna(inplace=True)
        else:
            df = None

        return df

    def resample_data(self, ohlcv, timerange):
        df = pd.DataFrame(ohlcv)
        if not df.empty:

            # Convert unix timestamp to datetime object
            df["timestamp"] = pd.to_datetime(
                df["timestamp"].astype(float), utc=True, origin="unix", unit="ms"
            )
            # Set datetime index
            df = df.set_index("timestamp")

            # Resample to the configured timerange
            if "m" in timerange:
                interval, range = timerange.split("m")
                timerange = f"{interval}Min"

            df_resample = df.resample(timerange).agg(
                {
                    "open": "first",
                    "high": "max",
                    "close": "last",
                    "low": "min",
                    "volume": "sum",
                }
            )

            # Reset index after resample
            df_resample.reset_index(inplace=True)

            # Convert datetime object back to a unix timestamp
            df_resample["timestamp"] = df_resample["timestamp"].astype(int)
            df_resample["timestamp"] = df_resample["timestamp"].div(10**9)

            # Clear empty values
            df_resample.dropna(inplace=True)

            return df_resample
        else:
            logging.error("No historic data available yet for symbol")

            return None
