import helper
import talib
import pandas as pd
import numpy as np
from service.data import Data
from asyncache import cached
from cachetools import TTLCache

data = Data()

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")


class Indicators:

    async def calculate_bbands_cross(self, symbol, timerange, length):
        result = "none"
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            df["upper_band"], df["middle_band"], df["lower_band"] = talib.BBANDS(
                df["close"], timeperiod=length
            )
            df.dropna(subset=["upper_band", "middle_band", "lower_band"], inplace=True)
            percent_difference_downtrend = 0
            percent_difference_uptrend = 0
            if df["close"].iloc[-2] < df["lower_band"].iloc[-2]:
                percent_difference_downtrend = (
                    abs(df["lower_band"].iloc[-2] - df["close"].iloc[-2])
                    / ((df["lower_band"].iloc[-2] + df["close"].iloc[-2]) / 2)
                    * 10
                )
            if df["close"].iloc[-1] > df["lower_band"].iloc[-1]:
                percent_difference_uptrend = (
                    abs(df["lower_band"].iloc[-1] - df["close"].iloc[-1])
                    / ((df["lower_band"].iloc[-1] + df["close"].iloc[-1]) / 2)
                    * 100
                )

            logging.debug(
                f"Symbol: {symbol}, Price: {df["close"].iloc[-1]}, LowerBand: {df["lower_band"].iloc[-1]}"
            )
            logging.debug(
                f"Symbol: {symbol}, downtrend: {percent_difference_downtrend}, uptrend: {percent_difference_uptrend}"
            )

            if percent_difference_downtrend > 0.1 and (
                percent_difference_uptrend > 0.1 and percent_difference_uptrend < 0.5
            ):
                result = True
        except Exception as e:
            logging.error(f"BBANDS cross cannot be calculated for {symbol}. Cause: {e}")

        return result

    async def calculate_ema(self, symbol, timerange, lengths):
        ema = {}
        try:
            max_length = max(lengths)
            df_raw = await data.get_data_for_pair(symbol, timerange, max_length)
            df = data.resample_data(df_raw, timerange)
            for length in lengths:
                length_key = f"ema_{str(length)}"
                ema[length_key] = (
                    talib.EMA(df["close"], timeperiod=length).dropna().iloc[-1]
                )
        except Exception as e:
            logging.error(f"EMA cannot be calculated for {symbol}. Cause: {e}")
        return ema

    async def get_close_price(self, symbol, timerange, length):
        df_raw = await data.get_data_for_pair(symbol, timerange, length)
        df = data.resample_data(df_raw, timerange)
        return df["close"]

    async def calculate_ema_slope(self, symbol, timerange, length):
        result = "none"
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
        result = "none"
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, 21)
            df = data.resample_data(df_raw, timerange)
            df["ema_short"] = talib.EMA(df["close"], timeperiod=9)
            df["ema_long"] = talib.EMA(df["close"], timeperiod=21)
            df.dropna(subset=["ema_short", "ema_long"], inplace=True)

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
        result = "none"
        try:
            df_raw = await data.get_data_for_pair(symbol, timerange, length)
            df = data.resample_data(df_raw, timerange)
            rsi = talib.RSI(df["close"], timeperiod=length).dropna().iloc[-1]
        except Exception as e:
            logging.error("Error getting RSI data. Cause: {e}")
        return rsi

    async def calculate_rsi_slope(self, symbol, timerange, length):
        result = "none"
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
            logging.error(f"RSI SLOPE cannot be calculated for {symbol}. Cause: {e}")
        return result

    async def calculate_24h_volume(self, symbol):
        result = "none"
        try:
            df_raw = await data.get_data_for_pair(symbol, "1D", 1)
            df = data.resample_data(df_raw, "1h").rolling(window=24).mean()
            quote_volume = df.apply(lambda row: (row["close"] * row["volume"]), axis=1)
            result = quote_volume.sum()
        except Exception as e:
            logging.error(f"24h volume cannot be calculated for {symbol}. Cause: {e}")
        return result

    @cached(cache=TTLCache(maxsize=1024, ttl=10))
    async def calculate_btc_pulse(self, currency, timerange):
        result = True
        try:
            symbol = "BTC" + "/" + currency
            df_raw = await data.get_data_for_pair(symbol, timerange, 50)
            df = data.resample_data(df_raw, timerange)
            df["ema_9"] = talib.EMA(df["close"], timeperiod=9)
            df["ema_50"] = talib.EMA(df["close"], timeperiod=50)
            ema9 = df["ema_9"].dropna().iloc[-1]
            ema50 = df["ema_50"].dropna().iloc[-1]
            price_action = (np.log(df["close"].pct_change(3) + 1)) * 100
            price_action = price_action.dropna().iloc[-1]

            if (price_action < -1) or (ema50 > ema9):
                result = False
            else:
                result = True
        except Exception as e:
            logging.error(
                f"BTC Pulse cannot be calculated, because we don't have enough history data. Cause: {e}"
            )

        return result

    async def calculate_ichimoku_cross(self, symbol, timerange):
        result = "none"
        try:
            # Data
            df_raw = await data.get_data_for_pair(symbol, timerange, 200)
            df = data.resample_data(df_raw, timerange)

            # Tenkan Sen (Conversation line)
            tenkan_sen_length = 20
            tenkan_sen_high = df["high"].rolling(tenkan_sen_length).max()
            tenkan_sen_low = df["low"].rolling(tenkan_sen_length).min()
            df["tenkan_sen"] = (tenkan_sen_high + tenkan_sen_low) / 2

            # Kijun Sen (Base Line)
            kijun_sen_length = 60
            kijun_sen_high = df["high"].rolling(kijun_sen_length).max()
            kijun_sen_low = df["low"].rolling(kijun_sen_length).min()
            df["kijun_sen"] = (kijun_sen_high + kijun_sen_low) / 2

            # Senkou Span A (Leading Span A)
            # senkou_span_a_ahead = 30
            # df["senkou_span_a"] = ((df["tenkan_sen"] + df["kijun_sen"]) / 2).shift(
            #     senkou_span_a_ahead
            # )
            df["senkou_span_a"] = (df["tenkan_sen"] + df["kijun_sen"]) / 2

            # Senkou Span B (Leading Span B)
            senkou_span_b_length = 120
            # senkou_span_b_ahead = 30
            senkou_span_b_high = df["high"].rolling(senkou_span_b_length).max()
            senkou_span_b_low = df["low"].rolling(senkou_span_b_length).min()
            # df["senkou_span_b"] = ((senkou_span_b_high + senkou_span_b_low) / 2).shift(
            #     senkou_span_b_ahead
            # )
            df["senkou_span_b"] = (senkou_span_b_high + senkou_span_b_low) / 2

            # Conditions
            cond1 = (df["kijun_sen"] > df["senkou_span_a"]) & (
                df["kijun_sen"] > df["senkou_span_b"]
            )
            cond2 = df["tenkan_sen"] > df["kijun_sen"]
            cond3 = df["close"] > df["tenkan_sen"]

            # All conditions now
            all_now = cond1 & cond2 & cond3

            # All conditions previous
            all_prev = all_now.shift(1).fillna(False).astype(bool)

            # Trigger only when going from False → True
            df["signal"] = all_now & (~all_prev)

            if df["signal"].iloc[-1]:
                result = "up"

            logging.debug(
                f"Base Line: {df["kijun_sen"].iloc[-1]} Conversation Line: {df["tenkan_sen"].iloc[-1]} Leading Span A: {df["senkou_span_a"].iloc[-1]} Leading Span B: {df["senkou_span_b"].iloc[-1]} Signal: {df["signal"].iloc[-1]}"
            )

            # if (
            #     # Baseline > Leading Span A and Leading Span B
            #     (
            #         df["kijun_sen"].iloc[-1] > df["senkou_span_a"].iloc[-1]
            #         and df["kijun_sen"].iloc[-1] > df["senkou_span_b"].iloc[-1]
            #     )
            #     # Conversation Line > Base Line
            #     and (df["tenkan_sen"].iloc[-1] > df["kijun_sen"].iloc[-1])
            #     # Close Price > Conversation Line
            #     and (df["close"].iloc[-2] > df["tenkan_sen"].iloc[-2])
            # ):
            #     logging.debug(
            #         "Reached strategy goals checking if crossed previous candle..."
            #     )
            #     # Check if baseline crossed one of the leading spans in the last candle
            #     # TODO Check works if going down too - check with low and close to find out if chart goes up or down!
            #     if (
            #         df["kijun_sen"].iloc[-2] < df["senkou_span_a"].iloc[-2]
            #         or df["kijun_sen"].iloc[-2] < df["senkou_span_b"].iloc[-2]
            #     ) or (df["low"].iloc[-2] < df["tenkan_sen"].iloc[-2]):
            #         logging.debug(
            #             f"Baseline/Conversation line crossed leading spans for {symbol}"
            #         )
            #         result = "up"
        except Exception as e:
            logging.error(
                f"Ichimoku Cross cannot be calculated for {symbol}. Cause: {e}"
            )
        return result
