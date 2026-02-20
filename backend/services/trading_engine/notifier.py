from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _NotifyItem:
    kind: Literal["text", "file"]
    payload: str
    caption: str | None = None
    retry_count: int = 0


class BestEffortNotifier:
    """Best-effort notification queue. Failures never raise to caller."""

    def __init__(
        self,
        *,
        send_text: Callable[[str], bool] | None = None,
        send_file: Callable[[str, str | None], bool] | None = None,
        max_retry: int = 3,
    ) -> None:
        self._send_text = send_text
        self._send_file = send_file
        self._max_retry = max(0, int(max_retry))
        self._queue: queue.Queue[_NotifyItem] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue_text(self, text: str) -> None:
        self._queue.put(_NotifyItem(kind="text", payload=text))

    def enqueue_file(self, path: str, caption: str | None = None) -> None:
        self._queue.put(_NotifyItem(kind="file", payload=path, caption=caption))

    def flush(self, timeout_sec: float = 2.0) -> None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self._queue.empty():
                return
            time.sleep(0.05)

    def close(self, timeout_sec: float = 2.0) -> None:
        self.flush(timeout_sec=timeout_sec)
        self._stop.set()
        self._thread.join(timeout=timeout_sec)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            ok = self._deliver(item)
            if not ok and item.retry_count < self._max_retry:
                item.retry_count += 1
                self._queue.put(item)
            self._queue.task_done()

    def _deliver(self, item: _NotifyItem) -> bool:
        try:
            if item.kind == "text":
                if not self._send_text:
                    return True
                return bool(self._send_text(item.payload))
            if not self._send_file:
                return True
            return bool(self._send_file(item.payload, item.caption))
        except Exception as exc:
            logger.warning("notification failed kind=%s error=%s", item.kind, exc)
            return False
