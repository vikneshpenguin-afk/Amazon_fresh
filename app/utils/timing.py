import time
from typing import Optional


class Timer:
    """Utility timer for tracking execution duration."""
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def stop(self) -> float:
        self.end_time = time.perf_counter()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        current = self.end_time if self.end_time is not None else time.perf_counter()
        return current - self.start_time

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
