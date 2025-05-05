import helper
import talib
import pandas as pd
from service.data import Data

data = Data()

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")


class Indicators:

    async def calculate_ema(self, symbol, timerange, length):
        df_raw = await data.get_data_for_pair(symbol, timerange, length)
        df = data.resample_data(df_raw, timerange)

        try:
            ema = talib.EMA(df["close"], timeperiod=length)
            ema = ema.dropna()
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
        df_raw = await data.get_data_for_pair(symbol, timerange, 21)
        df = data.resample_data(df_raw, timerange)
        df["ema_short"] = talib.EMA(df["close"], timeperiod=9)
        df["ema_long"] = talib.EMA(df["close"], timeperiod=21)
        df.dropna(subset=["ema_short", "ema_long"], inplace=True)

        try:

            if (
                df.iloc[-2]["ema_short"] <= df.iloc[-2]["ema_long"]
                and df.iloc[-1]["ema_short"] >= df.iloc[-1]["ema_long"]
            ):
                result = "up"
            elif (
                df.iloc[-2]["ema_short"] >= df.iloc[-2]["ema_long"]
                and df.iloc[-1]["ema_short"] <= df.iloc[-1]["ema_long"]
            ):
                result = "down"
            else:
                result = "none"

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
            logging.error(f"RSI SLOPE cannot be calculated for {symbol}. Cause: {e}")
        return result
