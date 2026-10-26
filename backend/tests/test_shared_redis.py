"""Shared Redis survives the instance that first launched it."""

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from service import redis as redis_service


def test_existing_redis_is_reused_without_spawning(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(redis_service, "_is_redis_running", lambda: True)
    monkeypatch.setattr(redis_service.subprocess, "Popen", spawn)
    assert redis_service.start_redis() is None
    spawn.assert_not_called()


def test_spawned_redis_is_detached_and_has_no_exit_cleanup(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    register = Mock()
    monkeypatch.setattr(redis_service, "_is_redis_running", lambda: False)
    monkeypatch.setattr(redis_service.subprocess, "Popen", spawn)
    monkeypatch.setattr(redis_service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(atexit, "register", register)
    assert redis_service.start_redis() is process
    assert spawn.call_args.kwargs["start_new_session"] is True
    assert spawn.call_args.kwargs["stdin"] == subprocess.DEVNULL
    register.assert_not_called()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_failed_startup_reaps_only_the_exited_child(monkeypatch):
    process = Mock()
    process.poll.return_value = 1
    monkeypatch.setattr(redis_service, "_is_redis_running", lambda: False)
    monkeypatch.setattr(redis_service.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(redis_service.time, "sleep", lambda _seconds: None)
    assert redis_service.start_redis() is None
    process.wait.assert_called_once_with()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="POSIX session isolation")
def test_shared_server_accepts_connections_after_launcher_exits(tmp_path):
    """Exercise real parent exit without touching the machine's Redis server."""
    address_file = tmp_path / "port"
    server = f"""
import socket
from pathlib import Path
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(30)
    Path({str(address_file)!r}).write_text(str(listener.getsockname()[1]))
    with listener.accept()[0] as connection:
        connection.sendall(b'+PONG\\r\\n')
"""
    launcher = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
from service import redis
real_spawn = redis.subprocess.Popen
redis._is_redis_running = lambda: False
redis.subprocess.Popen = lambda _args, **kwargs: real_spawn(
    [sys.executable, '-c', {server!r}], **kwargs
)
process = redis.start_redis()
print(process.pid, flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", launcher], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    child_pid = int(result.stdout.strip())
    try:
        deadline = time.monotonic() + 3
        while not address_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert address_file.exists(), "Server was stopped when its launcher exited"
        with socket.create_connection(
            ("127.0.0.1", int(address_file.read_text())), timeout=2
        ) as connection:
            assert connection.recv(16) == b"+PONG\r\n"
    finally:
        try:
            os.kill(child_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
