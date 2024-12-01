# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create (dynamic) DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address
- Configured API access on your exchange
- Python 3.10.x (not older - not newer for now)

## Installation
```pip install -r requirements.txt```

## Configuration (config.ini)
Name | Type | Mandatory | Values(default) | Description
------------ | ------------ | ------------ | ------------ | ------------
timezone | string | YES | (Europe/London) | Timezone used by the logging framework
debug | boolean | NO | (false) true  | Logging debugging information into various logs
port | integer | NO | (8120) | Port to use for the internal webserver (Must be port 80 for http and Tradingview use)
plugin | string | YES | (autocrypto) | Plugin to be used as signal for Moonwalker
plugin_settings | string | YES | . | Specific plugin settings for the chosen plugin
exchange | string | YES | (binance) | Used exchange for trading
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
dry_run | string | YES | (False) | If set to true no exchange orders will be made and the trade will be simulated
currency | string | YES | (USDT) | Trading pair to use
market | string | YES | (spot) | You can choose between spot or future trading
max_bots | integer | NO | (1) | Number of bots that can be active at the same time
trailing_tp | float | NO | (0) | Deviation between TP and TTP. For example, if you set 0.5 with a tp of 1.0 in the worst case it should sell at 0.5

## SymSignals signal setup

## ASAP signal setup

When you are ready with the configuration, copy the ``config.ini.example`` to ``config.ini`` and start the bot.

## Run
```python moonwalker.py```

## Logging
You can see information about the DCA and the TakeProfit (TP) status in the statistics.log. Other logs are available too (for exchange ...)


