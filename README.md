# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address and incoming access
- Configured API access on your exchange

## Installation
```pip install -r requirements.txt```

## Configuration (config.ini)
Name | Type | Mandatory | Values(default) | Description
------------ | ------------ | ------------ | ------------ | ------------
timezone | string | YES | (Europe/London) | Timezone used by the logging framework
debug | boolean | NO | (false) true  | Logging debugging information into the tvbot.log
port | integer | NO | (80) | Port to use for the internal webserver (Must be port 80 for http and Tradingview use)
plugin | string | YES | (tradingview) | Plugin to be used as signal for Moonwalker
token | uuid | YES | (a1234567-b123-c123-d123-e1234567890a) | Authentication token between external Service (for example TradingView) and Moonwalker
exchange | string | YES | (binance) | Used exchange for trading
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
sandbox | string | YES | (True) | If true is configured, the exchange module trades on the exchange testnet (if the exchange has one)
currency | string | YES | (USDT) | Trading pair to use
market | string | YES | (spot) | You can choose between spot or future trading
leverage | integer | NO | (1) | Leverage you like to use for future trading

## TV signal setup
In the message field you have to insert either the start or the stop signal (for DCA you only need the start signal). An example can be found in the ``config.ini.example``

When you are ready with the configuration, copy the ``config.ini.example`` to ``config.ini`` and start the bot.

## Run
```python moonwalker.py```


