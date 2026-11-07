"""
inventory.py - the Inventory class: owns all state and the batch operations.

Data structures we planned
---------------
  batches_by_id     dict  batch_id -> Batch                (hash table, O(1) lookup)
  lots_by_sku       dict  sku -> min-heap by expiry        (per-product FEFO heap)
  available_by_sku  dict  sku -> sellable units            (DESIGN CHANGE, see below)
"""

import itertools
from datetime import date, timedelta

from batch import Batch
from heap_manager import HeapManager


class Inventory:
    def __init__(self, expiry_buffer_days: int = 3) -> None:
        if expiry_buffer_days < 0:
            raise ValueError("expiry_buffer_days cannot be negative")
        self.expiry_buffer = timedelta(days=expiry_buffer_days)

        self.batches_by_id: dict[str, Batch] = {}
        self.heaps = HeapManager()
        self.available_by_sku: dict[str, int] = {}
        self.orders: dict[str, dict[str, int]] = {}

        # Global counter, so a deleted-then-reinserted batch ID never reuses
        # an old version number (old heap entries stay stale).
        self._versions = itertools.count(1)

    # Short names that match the assignment's component table.
    @property
    def lots_by_sku(self):
        return self.heaps.lots_by_sku

    # ============================================================ insert
    def insert_batch(self, batch_id: str, sku: str, quantity: int,
                     expiry: date, today: date) -> Batch:
        """Record a new delivery.  O(log n): dict insert + two heap pushes.

        Rejects duplicate IDs, non-positive quantities, and batches that are
        already at or past their sell_by date.
        """
       
        sell_by = expiry - self.expiry_buffer
        if sell_by <= today:
            raise ValueError(f"Batch {batch_id} cannot be sold: sell-by date {sell_by} has passed")

        batch = Batch(batch_id, sku, expiry, sell_by, quantity,
                      version=next(self._versions))
        self.batches_by_id[batch_id] = batch
        self.heaps.add_batch(batch)
        self.available_by_sku[sku] = self.available_by_sku.get(sku, 0) + quantity
        return batch

    # search
    def search_batch(self, batch_id: str) -> Batch | None:
        """Return the batch with this ID, or None if there is none.  O(1) average."""
        return self.batches_by_id.get(batch_id)

    # delete
    def delete_batch(self, batch_id: str) -> Batch:
        """Remove a batch (e.g. damaged or recalled stock).  O(1) average.

        Refuses if the batch still has reservations - cancel those orders
        first so no customer is silently left without stock. Its heap
        entries are not searched for; they become stale and are dropped
        lazily when they reach the top of a heap.
        """
        batch = self.batches_by_id.get(batch_id)
        if batch is None:
            raise ValueError(f"No batch {batch_id}")
        if batch.reserved > 0:
            raise ValueError(
                f"Batch {batch_id} has reservations, cancel them first")
        self.available_by_sku[batch.sku] -= batch.quantity - batch.reserved
        del self.batches_by_id[batch_id]
        return batch


# testing inventory operations
if __name__ == "__main__":
    print("Inventory module loaded")
    from datetime import date
    inv = Inventory()
    today = date(2024, 6, 1)
    try:
        batch = inv.insert_batch("B101", "milk", 10, date(2024, 6, 10), today)
        print(f"Inserted batch: {batch}")
        inv.delete_batch("B101")
    except ValueError as e:
        print(e)