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
plugin_type | string | YES | (external) | External is for plugins like Tradingview - which sends a signal to the bot
token | uuid | YES | (a1234567-b123-c123-d123-e1234567890a) | Authentication token between external Service (for example TradingView) and Moonwalker
exchange | string | YES | (binance) | Used exchange for trading
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
sandbox | string | YES | (True) | If true is configured, the exchange module trades ‚on the exchange testnet (if the exchange has one)
currency | string | YES | (USDT) | Trading pair to use
market | string | YES | (spot) | You can choose between spot or future trading
leverage | integer | NO | (1) | Leverage you like to use for future trading
max_bots | integer | NO | (1) | Number of bots that can be active at the same time

## Tradingview signal setup
### Examples for the "message" field in a TradingView alert:
``{ "email_token": "a1234567-b123-c123-d123-e1234567890a", "ticker": "{{ticker}}", "action": "close_long", "botname": "ftm_usdt"}``

``{ "email_token": "a1234567-b123-c123-d123-e1234567890a", "ticker": "{{ticker}}", "action": "open_long", "botname": "ftm_usdt"}``

In the message field you have to insert either the start or the stop signal (for DCA you only need the start signal).

In the webhook url of the alert you have to insert your bot ip - for example: http://yourip/tv Please take notice about the context /tv at the end!

When you are ready with the configuration, copy the ``config.ini.example`` to ``config.ini`` and start the bot.

## Run
```python moonwalker.py```

## Logging
You can see information about the DCA and the TakeProfit (TP) status in the ``moonwalker.log``


