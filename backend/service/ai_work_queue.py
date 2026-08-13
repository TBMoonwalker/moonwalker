"""Bounded lifecycle-owned queue for optional AI background work."""

import helper
from service.background_work_queue import BoundedWorkQueue

logging = helper.LoggerFactory.get_logger("logs/ai_trust.log", "ai_work_queue")


class AiWorkQueue(BoundedWorkQueue):
    """AI-specific configuration for the shared bounded work queue."""

    def __init__(self, *, capacity: int = 256, worker_count: int = 2) -> None:
        super().__init__(
            name="AI background work",
            task_prefix="ai",
            logger=logging,
            capacity=capacity,
            worker_count=worker_count,
        )


ai_work_queue = AiWorkQueue()
