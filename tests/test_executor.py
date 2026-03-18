from __future__ import annotations

import threading
import time
from typing import Callable

from server.executor import SerialCommandExecutor
from storage.engine import StorageEngine


class TrackingStorage(StorageEngine):
    def __init__(self) -> None:
        super().__init__()
        self._tracking_lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def set(self, key: str, value: str) -> None:
        self._enter_operation()
        try:
            time.sleep(0.01)
            super().set(key, value)
        finally:
            self._exit_operation()

    def get(self, key: str) -> str | None:
        self._enter_operation()
        try:
            time.sleep(0.01)
            return super().get(key)
        finally:
            self._exit_operation()

    def delete(self, key: str) -> bool:
        self._enter_operation()
        try:
            time.sleep(0.01)
            return super().delete(key)
        finally:
            self._exit_operation()

    def _enter_operation(self) -> None:
        with self._tracking_lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)

    def _exit_operation(self) -> None:
        with self._tracking_lock:
            self.active_calls -= 1


def test_executor_serializes_concurrent_command_submissions() -> None:
    storage = TrackingStorage()
    executor = SerialCommandExecutor(storage=storage)
    executor.start()

    barrier = threading.Barrier(6)
    responses: list[object] = []
    errors: list[BaseException] = []
    response_lock = threading.Lock()
    commands = [
        ["SET", "shared", "1"],
        ["GET", "shared"],
        ["SET", "shared", "2"],
        ["DEL", "shared"],
        ["GET", "shared"],
        ["SET", "shared", "3"],
    ]

    def worker(command: list[str]) -> None:
        try:
            barrier.wait(timeout=1)
            response = executor.execute(command, timeout=2)
            with response_lock:
                responses.append(response)
        except BaseException as exc:
            with response_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(command,)) for command in commands]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()

    executor.stop()

    assert not errors
    assert len(responses) == len(commands)
    assert storage.max_active_calls == 1


def test_executor_remains_safe_under_repeated_mixed_operations() -> None:
    executor = SerialCommandExecutor(storage=StorageEngine())
    executor.start()

    barrier = threading.Barrier(8)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def capture(fn: Callable[[], None]) -> None:
        try:
            barrier.wait(timeout=2)
            fn()
        except BaseException as exc:
            with errors_lock:
                errors.append(exc)

    def writer(worker_id: int) -> None:
        for value in range(100):
            assert executor.execute(["SET", "shared", f"{worker_id}-{value}"], timeout=2) == "OK"

    def reader() -> None:
        for _ in range(100):
            response = executor.execute(["GET", "shared"], timeout=2)
            assert response is None or isinstance(response, str)

    def deleter() -> None:
        for _ in range(100):
            response = executor.execute(["DEL", "shared"], timeout=2)
            assert response in {0, 1}

    threads = [
        threading.Thread(target=capture, args=(lambda wid=wid: writer(wid),))
        for wid in range(2)
    ]
    threads.extend(threading.Thread(target=capture, args=(reader,)) for _ in range(3))
    threads.extend(threading.Thread(target=capture, args=(deleter,)) for _ in range(3))

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    executor.stop()
    assert not errors
