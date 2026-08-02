"""Lifespan-owned queue for closed-trade replay archive repair."""

import helper
from service.background_work_queue import BoundedWorkQueue

logging = helper.LoggerFactory.get_logger(
    "logs/order_persistence.log",
    "replay_repair_queue",
)

replay_repair_queue = BoundedWorkQueue(
    name="Replay archive repair",
    task_prefix="replay-repair",
    logger=logging,
    capacity=128,
    worker_count=1,
)
