# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address and incoming access (if you like to use Tradingview)
- Configured API access on your exchange

## Installation
```pip install -r requirements.txt```

## Configuration (config.ini)
Name | Type | Mandatory | Values(default) | Description
------------ | ------------ | ------------ | ------------ | ------------
timezone | string | YES | (Europe/London) | Timezone used by the logging framework
debug | boolean | NO | (false) true  | Logging debugging information into various logs
port | integer | NO | (8120) | Port to use for the internal webserver (Must be port 80 for http and Tradingview use)
plugin | string | YES | (autocrypto) | Plugin to be used as signal for Moonwalker
plugin_type | string | YES | (internal) | External is for plugins like Tradingview - which sends a signal to the bot
plugin_settings | string | YES | . | Specific plugin settings for the chosen plugin
exchange | string | YES | (binance) | Used exchange for trading
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
dry_run | string | YES | (False) | If set to true no exchange orders will be made and the trade will be simulated
currency | string | YES | (USDT) | Trading pair to use
market | string | YES | (spot) | You can choose between spot or future trading
leverage | integer | NO | (1) | Leverage you like to use for future trading
margin_type | integer | NO | (isolated) | Margin type you like to use for future trading (crossed or isolated)
max_bots | integer | NO | (1) | Number of bots that can be active at the same time
trailing_tp | float | NO | (0) | Deviation between TP and TTP. For example, if you set 0.5 with a tp of 1.0 in the worst case it should sell at 0.5

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
You can see information about the DCA and the TakeProfit (TP) status in the statistics.log. Other logs are available too (for exchange ...)


