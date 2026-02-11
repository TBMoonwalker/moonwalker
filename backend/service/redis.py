"""Redis client and local subprocess lifecycle helpers."""

import atexit
import socket
import subprocess
import time

import redis.asyncio as redis


def _is_redis_running(host: str = "localhost", port: int = 6379) -> bool:
    """Return whether a Redis-compatible service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=0.5) as conn:
            conn.sendall(b"*1\r\n$4\r\nPING\r\n")
            return conn.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def stop_redis(proc: subprocess.Popen | None) -> None:
    """Terminate a spawned Redis process and wait to reap it."""
    if proc is None:
        return
    if proc.poll() is not None:
        # Ensure already-exited children are reaped.
        proc.wait()
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def start_redis() -> subprocess.Popen | None:
    """Start a local Redis server when no Redis instance is already available."""
    if _is_redis_running():
        return None

    proc = subprocess.Popen(
        ["redis-server", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Reap immediately if startup failed (e.g. address in use).
    time.sleep(0.2)
    if proc.poll() is not None:
        proc.wait()
        return None

    # Ensure spawned Redis stops when Python exits.
    atexit.register(stop_redis, proc)
    return proc


redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True,
)

CONFIG_CHANNEL = "config:changed"
