from __future__ import annotations

import csv
import io
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class CachedResult:
    columns: list[str]
    rows: list[list[str]]
    created_at: float = field(default_factory=time.time)
    user_id: int = 0


class ResultCache:
    def __init__(self, ttl_sec: int) -> None:
        self.ttl_sec = ttl_sec
        self._items: dict[str, CachedResult] = {}

    def put(
        self,
        user_id: int,
        columns: list[str],
        rows: list[list[str]],
    ) -> str:
        self.cleanup()
        run_id = uuid.uuid4().hex
        self._items[run_id] = CachedResult(
            columns=columns,
            rows=rows,
            user_id=user_id,
        )
        return run_id

    def get(self, run_id: str, user_id: int) -> CachedResult | None:
        self.cleanup()
        item = self._items.get(run_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def to_csv_bytes(self, item: CachedResult) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(item.columns)
        writer.writerows(item.rows)
        return buffer.getvalue().encode("utf-8-sig")

    def cleanup(self) -> None:
        now = time.time()
        expired = [
            key
            for key, item in self._items.items()
            if now - item.created_at > self.ttl_sec
        ]
        for key in expired:
            del self._items[key]
