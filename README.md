# TVBot
## Summary
TVBot can be used to start and stop deals using Tradingview alerts. It is also capable to create DCA deals (if the TV indicator makes use of them).

## Disclaimer
**TVBot is meant to be used for educational purposes only. Use with real funds at your own risk**

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
token | uuid | YES | (a1234567-b123-c123-d123-e1234567890a) | Authentication token between Tradingview and TVBot
exchange | string | YES | (binance) | Used exchange for trading
key | string | YES | () | API Key taken from the exchange you are using
secret | string | YES | () | API Secret taken from the exchange you are using
sandbox | string | YES | (True) | If true is configured, the exchange module trades on the exchange testnet (if the exchange has one)
currency | string | YES | (USDT) | Trading pair to use
market | string | YES | (spot) | You can choose between spot or future trading




## Run
```python main.py```


