"""Redis client and startup for the shared local server."""

import os
import socket
import subprocess
import time
import uuid

import redis.asyncio as redis


def _is_redis_running(host: str = "localhost", port: int = 6379) -> bool:
    """Return whether a Redis-compatible service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=0.5) as conn:
            conn.sendall(b"*1\r\n$4\r\nPING\r\n")
            return conn.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def start_redis() -> subprocess.Popen | None:
    """Reuse or launch Redis; its lifetime is independent of any one instance."""
    if _is_redis_running():
        return None

    proc = subprocess.Popen(
        ["redis-server", "--save", "", "--appendonly", "no"],
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Reap immediately if startup failed (e.g. address in use).
    time.sleep(0.2)
    if proc.poll() is not None:
        proc.wait()
        return None

    # Other Moonwalker installations may share this server. Never register
    # application-exit cleanup; a supervisor or the operator owns its lifetime.
    return proc


redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True,
)

_CONFIG_CHANNEL_SCOPE = os.getenv("MOONWALKER_CONFIG_CHANNEL_SCOPE") or str(
    uuid.uuid4()
)
CONFIG_CHANNEL = f"config:changed:{_CONFIG_CHANNEL_SCOPE}"
