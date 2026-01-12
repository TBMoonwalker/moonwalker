import redis.asyncio as redis
import subprocess
import atexit


def start_redis():
    """
    Start a local Redis server as a subprocess.
    """
    proc = subprocess.Popen(
        ["redis-server", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Ensure Redis stops when Python exits
    def cleanup():
        proc.terminate()

    atexit.register(cleanup)
    return proc


redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True,
)

CONFIG_CHANNEL = "config:changed"
