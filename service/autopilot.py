import helper

logging = helper.LoggerFactory.get_logger("logs/autopilot.log", "autopilot")


class Autopilot:
    def __init__(self):
        self.utils = helper.Utils()
        config = helper.Config()

        self.autopilot = config.get("autopilot", False)
        self.autopilot_max_fund = config.get("autopilot_max_fund", 0)
        self.autopilot_high_mad = config.get("autopilot_high_mad", 0)
        self.autopilot_high_tp = config.get("autopilot_high_tp", 0)
        self.autopilot_high_sl = config.get("autopilot_high_sl", 0)
        self.autopilot_high_sl_timeout = config.get("autopilot_high_sl_timeout", 0)
        self.autopilot_high_threshold = config.get("autopilot_high_threshold", False)
        self.autopilot_medium_mad = config.get("autopilot_medium_mad", 0)
        self.autopilot_medium_tp = config.get("autopilot_medium_tp", 0)
        self.autopilot_medium_sl = config.get("autopilot_medium_sl", 0)
        self.autopilot_medium_threshold = config.get(
            "autopilot_medium_threshold", False
        )

    async def calculate_trading_settings(self, funds_locked):
        trading_settings = {}
        if self.autopilot:
            # TODO - check what's happening if funds_locked are higher then max fund
            threshold_percent = (funds_locked / self.autopilot_max_fund) * 100

            if threshold_percent >= self.autopilot_high_threshold:
                logging.debug(
                    f"we reached autopilot high values - threshold: {threshold_percent}%"
                )
                trading_settings["mad"] = self.autopilot_high_mad
                trading_settings["tp"] = self.autopilot_high_tp
                trading_settings["sl"] = self.autopilot_high_sl
                trading_settings["sl_timeout"] = self.autopilot_high_sl_timeout
            elif threshold_percent >= self.autopilot_medium_threshold:
                logging.debug(
                    f"we reached autopilot medium values - threshold: {threshold_percent}%"
                )
                trading_settings["mad"] = self.autopilot_medium_mad
                trading_settings["tp"] = self.autopilot_medium_tp
                trading_settings["sl"] = self.autopilot_medium_sl

        return trading_settings
