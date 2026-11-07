from __future__ import annotations

import heapq
from datetime import date

from batch import Batch

HeapEntry = tuple[date, str, int]  # (date_key, batch_id, version)


class HeapManager:
    def __init__(self) -> None:
        self.lots_by_sku: dict[str, list[HeapEntry]] = {}
        self.expiry_events: list[HeapEntry] = []

    def add_batch(self, batch: Batch) -> None:
        """Add a batch to both the per-SKU FEFO heap and the store-wide expiry heap."""
        heapq.heappush(self.lots_by_sku.setdefault(batch.sku, []),
                       (batch.expiry, batch.batch_id, batch.version))
        heapq.heappush(self.expiry_events,
                       (batch.sell_by, batch.batch_id, batch.version))

    @staticmethod
    def live_batch(entry: HeapEntry, batches_by_id: dict[str, Batch]) -> Batch | None:
        """Return the batch if the heap entry is still valid; otherwise None."""
        batch = batches_by_id.get(entry[1])
        if batch is None or batch.version != entry[2]:
            return None
        return batch

    def fefo_allocation(self, sku: str, qty: int,
                        batches_by_id: dict[str, Batch]) -> dict[str, int] | None:
        """Plan the earliest-expiring batches needed to satisfy qty for one SKU.

        Returns a mapping of batch_id -> units, or None if the requested qty cannot
        be filled from currently live stock in the heaps.
        """
        if qty <= 0:
            return {}

        heap = self.lots_by_sku.get(sku, [])
        if not heap:
            return None

        plan: dict[str, int] = {}
        remaining = qty
        temp: list[HeapEntry] = []

        while heap and remaining > 0:
            entry = heapq.heappop(heap)
            batch = self.live_batch(entry, batches_by_id)
            if batch is None or batch.expired:
                continue

            available = batch.quantity - batch.reserved
            if available <= 0:
                continue

            take = min(remaining, available)
            plan[batch.batch_id] = plan.get(batch.batch_id, 0) + take
            remaining -= take

            # Keep the heap consistent while we inspect it.
            temp.append(entry)

        for entry in temp:
            heapq.heappush(heap, entry)

        if remaining > 0:
            return None
        return plan

    def pop_due(self, today: date, batches_by_id: dict[str, Batch]) -> list[Batch]:
        """Return all live batches whose sell-by date has arrived by today."""
        due: list[Batch] = []
        while self.expiry_events and self.expiry_events[0][0] <= today:
            entry = heapq.heappop(self.expiry_events)
            batch = self.live_batch(entry, batches_by_id)
            if batch is not None:
                due.append(batch)
        return due


if __name__ == "__main__":
    manager = HeapManager()
    batches_by_id = {}

    for batch in [
        Batch("B101", "milk", date(2024, 6, 1), date(2024, 5, 29), 10, version=1),
        Batch("B102", "milk", date(2024, 6, 15), date(2024, 6, 12), 5, version=2),
        Batch("B103", "eggs", date(2024, 6, 20), date(2024, 6, 17), 12, version=3),
    ]:
        batches_by_id[batch.batch_id] = batch
        manager.add_batch(batch)
        print(f"Added {batch.batch_id} ({batch.sku}) -> expiry={batch.expiry}, sell_by={batch.sell_by}")

    print("\nPer-SKU heap:")
    for sku, heap in manager.lots_by_sku.items():
        print(f"  {sku}: {heap}")
    print(f"Store-wide expiry heap: {manager.expiry_events}")

    print("\nFEFO allocation for milk = 12 units:")
    allocation = manager.fefo_allocation("milk", 12, batches_by_id)
    print(allocation)

    print("\nPop due batches for today 2024-05-29:")
    due = manager.pop_due(date(2024, 5, 29), batches_by_id)
    for batch in due:
        print(f"  due: {batch.batch_id} ({batch.sku}) expires {batch.expiry}")
    print(f"Remaining expiry heap: {manager.expiry_events}")