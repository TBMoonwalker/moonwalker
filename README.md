# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create (dynamic) DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address
- Configured API access on your exchange
- Python > 3.10.x

## Installation
```pip install -r requirements.txt```

### TA-Lib dependency

You also need to install the ta-lib library for your OS. Please see - https://ta-lib.org/install/#linux-debian-packages

## Configuration (config.ini)
Name | Type | Mandatory | Values(default) | Description
------------ | ------------ | ------------ | ------------ | ------------
timezone | string | YES | (Europe/London) | Timezone used by the logging framework
debug | boolean | NO | (false) true  | Logging debugging information into various logs
port | integer | NO | (8120) | Port to use for the internal webserver (Must be port 80 for http and Tradingview use)
plugin | string | YES | (sym_signals) | Plugin to be used as signal for Moonwalker
plugin_settings | string | YES | . | Specific plugin settings for the chosen plugin (see SymSignals signal setup)
pair_allowlist | string | NO |  | Specify which pairs are explicitely allowed for trading
pair_denylist | string | NO |  | Specify which pairs are explicitely denied for trading
exchange | string | YES | (binance) | Used exchange for trading
timeframe | string | NO | (1m) | Range of the ticker data for price calculation through websocket
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
password | string | NO | () | API Password taken from the exchange you are using - Not needed by every exchange
dry_run | string | NO | (True) | If set to true no exchange orders will be made and the trade will be simulated
currency | string | YES | (USDT) | Trading pair to use
market | string | NO | (spot) | Only spot trading is possible now (default value)
fee_deduction | boolean | YES | (False) | If True - the exchange token for fee deduction is used for trading fees. For example BNB on Binance.
dca | boolean | YES | (True) | Activates DCA
dynamic_dca | boolean | NO | (False) | Activates dynamic DCA. Attention - this works together with the configuration setting "ws_url" and only works with Moonloader right now!
dca_strategy | boolean | NO | (tothemoon) | Configures the specific strategy for dynamic DCA
dca_timeframe | string | NO | (1m) | Range of the indicator calculation for the dynamic DCA strategy
trailing_tp | float | NO | (0) | Deviation between TP and TTP. For example, if you set 0.5 with a tp of 1.0 in the worst case it should sell at 0.5
max_bots | integer | NO | (1) | Number of bots that can be active at the same time
bo | integer | YES | (10) | Base Order amount
so | integer | NO | () | Safety Order amount
sos | integer | YES | () | Price deviation for open safety orders
ss | integer | YES | () | Safety order step scale
os | integer | YES | () | Safety order volume scale
mstc | integer | NO | () | Max safety orders count
tp | integer | YES | (1) | Take profit in percent
sl | integer | NO | (1) | Stop loss in percent
housekeeping_interval | integer | NO | 48 | Minimum interval for indicator ticker caching
history_data | integer | NO | 3 | Minimum interval for history data - needed for dynamic dca

## SymSignals signal setup
``plugin_settings = {"api_url": "https://stream.3cqs.com", "api_key": "your api key", "api_version": "api version", "allowed_signals": [signalid, signalid]}``

The available signal id's for ``allowed_signals`` can be found from https://3cqs.com/home/faq/.

For example, ``allowed_signals[12, 2]`` configures SymRank Top 10 and SymRank Top30 as available signals for trade.

## ASAP signal setup

When you are ready with the configuration, copy the ``config.ini.example`` to ``config.ini`` and start the bot.

## Run
```python app.py```

## Logging
You can see information about the DCA and the TakeProfit (TP) status in the statistics.log. Other logs are available too (for exchange ...)


