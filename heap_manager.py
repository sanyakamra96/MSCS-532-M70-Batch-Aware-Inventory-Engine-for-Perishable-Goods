from __future__ import annotations

import heapq
from datetime import date

from batch import Batch

HeapEntry = tuple[date, str, int]   # (date key, batch_id, version)


class HeapManager:
    def __init__(self) -> None:
        self.lots_by_sku: dict[str, list[HeapEntry]] = {}
        self.expiry_events: list[HeapEntry] = []

    # ------------------------------------------------------------------ add
    def add_batch(self, batch: Batch) -> None:
        """Push a new batch onto its product heap and the store-wide heap.
        O(log n) - two heap pushes."""
        heapq.heappush(self.lots_by_sku.setdefault(batch.sku, []),
                       (batch.expiry, batch.batch_id, batch.version))
        heapq.heappush(self.expiry_events,
                       (batch.sell_by, batch.batch_id, batch.version))

    # stale
    @staticmethod
    def live_batch(entry: HeapEntry, batches_by_id: dict[str, Batch]) -> Batch | None:
        """Return the batch an entry points to, or None if the entry is stale
        (batch deleted, or its version changed since the entry was pushed). O(1)."""
        batch = batches_by_id.get(entry[1])
        if batch is None or batch.version != entry[2]:
            return None
        return batch

    # expiration
    def pop_due(self, today: date, batches_by_id: dict[str, Batch]) -> list[Batch]:
        """Pop every entry whose sell_by date has arrived (sell_by <= today)
        and return the live batches among them, earliest first.
        O(d log n), where d = number of entries popped (only those that are due)."""
        due: list[Batch] = []
        heap = self.expiry_events
        while heap and heap[0][0] <= today:
            entry = heapq.heappop(heap)
            batch = self.live_batch(entry, batches_by_id)
            if batch is not None:
                due.append(batch)
        return due




if __name__ == "__main__":
    manager = HeapManager()

    batches = [
        Batch("B101", "milk", date(2024, 6, 1), date(2024, 5, 29), 10, version=1),
        Batch("B102", "milk", date(2024, 6, 15), date(2024, 6, 12), 5, version=2),
        Batch("B103", "eggs", date(2024, 6, 20), date(2024, 6, 17), 12, version=3),
    ]

    for batch in batches:
        manager.add_batch(batch)
        print(f"Added {batch.batch_id} ({batch.sku}) -> lots_by_sku={manager.lots_by_sku}")
        print(f"Expiry heap: {manager.expiry_events}")

    today = date(2024, 6, 1)
    due = manager.pop_due(today, {
        batch.batch_id: batch for batch in batches
    })
    print(f"Due on {today}: {[batch.batch_id for batch in due]}")
    print(f"Remaining expiry heap: {manager.expiry_events}")