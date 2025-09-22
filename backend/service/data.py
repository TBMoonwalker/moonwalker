import ccxt.pro as ccxtpro
import ccxt as ccxt
import helper
import model
import pandas as pd
from datetime import datetime, timedelta

logging = helper.LoggerFactory.get_logger("logs/data.log", "data")


class Data:
    def __init__(self):
        config = helper.Config()
        utils = helper.Utils()
        self.utils = utils
        self.history_data = config.get("history_from_data", 3)
        self.exchange_id = config.get("exchange")
        self.exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = self.exchange_class(
            {
                "apiKey": config.get("key"),
                "secret": config.get("secret"),
                "options": {
                    "defaultType": config.get("market", "spot"),
                },
            },
        )
        self.exchange.set_sandbox_mode(config.get("sandbox", False))
        self.market = config.get("market", "spot")
        self.timeframe = config.get("timeframe", "1m")
        self.currency = config.get("currency").upper()

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

    async def delete_ticker_data_for_trades(self, symbol):
        try:
            query = await model.Tickers.filter(symbol=f"{symbol}").delete()
            logging.info(f"Delete {query} entries for sold symbol {symbol}")
            return True
        except Exception as e:
            logging.error(f"Error deleting old ticker data for symbol {symbol}: {e}")

        return False

    async def add_history_data_for_symbol(self, symbol):
        # symbol_list = await self.get_ticker_symbol_list()
        # logging.debug(f"Symbol list: {symbol_list}")
        # if symbol not in symbol_list:
        if await self.delete_ticker_data_for_trades(symbol):
            try:
                await self.fetch_history_data_for_symbol(symbol)
                logging.info(f"Added history for {symbol}")
                return True
            except Exception as e:
                logging.error(f"Error adding history for {symbol}. Cause: {e}")

        return False

    async def fetch_history_data_for_symbol(self, symbol):
        ohlcv = []
        from_date = "{:%Y-%m-%d %H:%M:%S}".format(
            datetime.now() - timedelta(days=self.history_data)
        )
        try:
            from_ts = self.exchange.parse8601(from_date)
            ohlcv_data = await self.exchange.fetch_ohlcv(
                symbol, self.timeframe, since=from_ts, limit=1000
            )
            await self.exchange.close()
            while True:
                from_ts = ohlcv_data[-1][0]
                new_ohlcv = await self.exchange.fetch_ohlcv(
                    symbol, self.timeframe, since=from_ts, limit=1000
                )
                ohlcv_data.extend(new_ohlcv)
                if len(new_ohlcv) != 1000:
                    break
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

        except ccxt.NetworkError as e:
            logging.error(
                f"Error fetching historical data from Exchange due to a network error: {e}"
            )
        except ccxt.ExchangeError as e:
            logging.error(
                f"Error fetching historical data from Exchange due to an exchange error: {e}"
            )
        except Exception as e:
            logging.error(f"Error fetching historical data from Exchange. Cause: {e}")

        await self.exchange.close()

    async def get_ohlcv_for_pair(self, pair, timerange, timestamp_start, offset):
        # 600000 --> 60 minutes in milliseconds before
        # start_date = datetime.fromtimestamp(((float(timestamp_start) - 600000) / 1000.0),UTC,)
        symbol = self.utils.split_symbol(pair, self.currency)
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
        symbol = self.utils.split_symbol(pair, self.currency)
        start_date = self.__calculate_min_candle_date(timerange, length)
        query = (
            await model.Tickers.filter(symbol=symbol)
            .filter(timestamp__gt=start_date)
            .values()
        )

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
