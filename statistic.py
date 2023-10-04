from logger import LoggerFactory


class Statistic:
    def __init__(self, stats, loglevel):
        Statistic.stats = stats

        Statistic.logging = LoggerFactory.get_logger(
            "statistics.log", "statistic", log_level=loglevel
        )
        Statistic.logging.info("Initialized")

    async def __process_stats(self, stats):
        Statistic.logging.debug(f"New statistic input: {stats}")

    async def run(self):
        while True:
            stats = await Statistic.stats.get()
            await self.__process_stats(stats)
