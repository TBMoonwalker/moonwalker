import helper
import talib
from service.data import Data

data = Data()

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")


class Indicators:

    async def calculate_ema(self, symbol, timerange, length):
        df_raw = await data.get_data_for_pair(symbol, timerange, length)
        df = data.resample_data(df_raw, timerange)

        try:
            ema = talib.EMA(df["close"], timeperiod=length)
            ema = ema.dropna().iloc[-1]
        except Exception as e:
            logging.error(f"EMA cannot be calculated for {symbol}. Cause: {e}")
            ema = None

        return ema

    async def calculate_ema_slope(self, symbol, timerange, length):
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            ema = talib.EMA(df["close"], timeperiod=length)
            ema_slope = ema.diff()
            ema_last_slope = ema_slope.dropna().iloc[-1]
            if ema_last_slope:
                if ema_last_slope > 0:
                    categories = "upward"
                elif ema_last_slope < 0:
                    categories = "downward"
                else:
                    categories = "flat"
            result = categories
        except Exception as e:
            result = None
            logging.error(f"EMA SLOPE cannot be calculated for {symbol}. Cause: {e}")
        return result

    async def calculate_ema_distance(self, symbol, timerange, length):
        result = False
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            ema = talib.EMA(df["close"], timeperiod=length)
            ema = ema.dropna().iloc[-1]
            close_price = df["close"].dropna().iloc[-1]
            percentage_diff = abs(close_price - ema) / ema * 100
            logging.debug(
                f"close_price: {close_price}, ema: {ema}, percentage diff: {percentage_diff}"
            )
            if percentage_diff < 2:
                result = True
        except Exception as e:
            logging.error(f"EMA Distance cannot be calculated for {symbol}. Cause: {e}")
        return result

    async def calculate_ema_cross(self, symbol, timerange):
        result = None
        ema_9 = await self.calculate_ema(symbol, timerange, 9)
        ema_50 = await self.calculate_ema(symbol, timerange, 50)

        logging.debug(f"EMA20: {ema_9}, EMA50: {ema_50}")

        try:
            if ema_9 > ema_50:
                result = "up"
            elif ema_9 < ema_50:
                result = "down"
        except Exception as e:
            logging.error(f"EMA Cross cannot be calculated for {symbol}. Cause: {e}")

        return result

    async def calculate_rsi(self, symbol, timerange, length):
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            rsi = talib.RSI(df["close"], timeperiod=length).dropna().iloc[-1]
        except Exception as e:
            logging.error("Error getting RSI data. Cause: {e}")
            rsi = None
        return rsi

    async def calculate_rsi_slope(self, symbol, timerange, length):
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            rsi = talib.RSI(df["close"], timeperiod=length)
            rsi_slope = rsi.diff()
            rsi_last_slope = rsi_slope.dropna().iloc[-1]
            categories = "flat"
            if rsi_last_slope:
                if rsi_last_slope > 0:
                    categories = "upward"
                elif rsi_last_slope < 0:
                    categories = "downward"
            result = categories
        except Exception as e:
            result = None
            Indicators.logging.info(
                f"RSI SLOPE cannot be calculated for {symbol}. Cause: {e}"
            )
        return result
