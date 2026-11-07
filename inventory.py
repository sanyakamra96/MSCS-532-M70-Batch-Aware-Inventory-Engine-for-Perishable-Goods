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
from typing import TypedDict

from batch import Batch, check_quantity
from heap_manager import HeapManager


class ExpiryReport(TypedDict):
    """Records the order holds attached to a batch when it expires.

    This is used for reconciliation: if a batch is no longer sellable, we want
    to know which customer reservations or holds were tied to it and what SKU
    they correspond to.
    """

    batch_id: str
    sku: str
    sell_by: date
    orders: dict[str, int]


class Inventory:
    """Central store for all batch data and inventory availability.

    This class owns the canonical batch dictionary, product availability totals,
    and expiry management logic. It acts as the main coordinator between batch
    records and the heap-based expiry system.
    """

    def __init__(self, expiry_buffer_days: int = 3) -> None:
        """Initialize the inventory and configure the expiry safety buffer.

        The buffer means a batch is treated as expiring a few days before its
        actual sell-by date, preventing sales of product that is close to being
        unsafely old.
        """
        if expiry_buffer_days < 0:
            raise ValueError("expiry_buffer_days cannot be negative")
        self.expiry_buffer = timedelta(days=expiry_buffer_days)

        # batches_by_id is the main lookup table for all active batches.
        # It allows O(1) average-time access by batch ID.
        self.batches_by_id: dict[str, Batch] = {}

        # HeapManager keeps the event and FEFO-style expiry structures in sync.
        self.heaps = HeapManager()

        # available_by_sku stores how many sellable units remain for each SKU.
        self.available_by_sku: dict[str, int] = {}

        # orders tracks the reservation/hold detail for each SKU.
        self.orders: dict[str, dict[str, int]] = {}

        # This holds any expiry reconciliation reports waiting to be processed.
        self._pending_expiry_reports: list[ExpiryReport] = []

        # Global counter, so a deleted-then-reinserted batch ID never reuses
        # an old version number (old heap entries stay stale).
        self._versions = itertools.count(1)

    # Short names that match the assignment's component table.
    @property
    def lots_by_sku(self):
        """Expose the per-SKU FEFO heaps for other parts of the system."""
        return self.heaps.lots_by_sku

    @property
    def expiry_events(self):
        """Expose the expiry event heap for processing or inspection."""
        return self.heaps.expiry_events

    def new_version(self) -> int:
        """Return a version that cannot match any earlier heap entry."""
        return next(self._versions)

    # ============================================================ insert
    def insert_batch(self, batch_id: str, sku: str, quantity: int,
                     expiry: date, today: date) -> Batch:
        """Record a new delivery. O(log n): dict insert + two heap pushes.

        Rejects duplicate IDs, non-positive quantities, and batches that are
        already at or past their sell_by date.
        """
        # A batch ID must be unique; duplicate IDs would cause overwriting data.
        if batch_id in self.batches_by_id:
            raise ValueError(f"Batch {batch_id} already exists")

        # Validate the quantity is a valid positive amount.
        check_quantity(quantity)

        # Current sell-by date is offset by the configured expiry buffer.
        sell_by = expiry - self.expiry_buffer
        if sell_by <= today:
            raise ValueError(f"Batch {batch_id} cannot be sold: sell-by date {sell_by} has passed")

        # Build the batch with a unique version to keep stale heap records from
        # matching active entries after an update or deletion.
        batch = Batch(batch_id, sku, expiry, sell_by, quantity,
                      version=self.new_version())

        # Add the batch to the authoritative store and the heap-based expiry
        # structures used for FEFO ordering and expiration checks.
        self.batches_by_id[batch_id] = batch
        self.heaps.add_batch(batch)

        # Increase stock available for the SKU by the full batch quantity.
        self.available_by_sku[sku] = self.available_by_sku.get(sku, 0) + quantity
        return batch

    def available(self, sku: str, today: date) -> int:
        """Return sellable stock for a SKU after expiring any due batches."""
        # Expirations are evaluated before the availability check so callers see
        # a current snapshot of stock, not stale sellable units.
        self.expire_due(today)
        return self.available_by_sku.get(sku, 0)

    def expire_due(self, today: date) -> list[Batch]:
        """Mark due batches unsellable and retain reports until collected."""
        # Ask the heap manager for any batches whose effective sell-by date has
        # passed, excluding stale heap entries that no longer match current data.
        due_batches = self.heaps.pop_due(today, self.batches_by_id)

        # Update the SKU totals and batch state for each expired batch.
        for batch in due_batches:
            # Remove its remaining available quantity from the SKU total.
            self.available_by_sku[batch.sku] -= batch.available

            # Mark the batch expired so it is no longer considered sellable.
            batch.expired = True

            # Bump the version so stale heap entries become invalid immediately.
            batch.version = self.new_version()

            # Record a report for any still-allocated order holds tied to this batch.
            if batch.quantity > 0:
                self._pending_expiry_reports.append({
                    "batch_id": batch.batch_id,
                    "sku": batch.sku,
                    "sell_by": batch.sell_by,
                    "orders": dict(batch.holds),
                })
        return due_batches

    def process_expired(self, today: date) -> list[ExpiryReport]:
        """Expire due batches and return uncollected reconciliation reports."""
        # Clear any pending expiry reports after returning them so the queue is
        # drained in a controlled way.
        self.expire_due(today)
        reports = self._pending_expiry_reports
        self._pending_expiry_reports = []
        return reports

    # search
    def search_batch(self, batch_id: str) -> Batch | None:
        """Return the batch with this ID, or None if there is none. O(1) average."""
        return self.batches_by_id.get(batch_id)

    # delete
    def delete_batch(self, batch_id: str) -> Batch:
        """Remove a batch (e.g. damaged or recalled stock). O(1) average.

        Refuses if the batch still has reservations - cancel those orders
        first so no customer is silently left without stock. Its heap
        entries are not searched for; they become stale and are dropped
        lazily when they reach the top of a heap.
        """
        # Fetch the batch from the authoritative dictionary.
        batch = self.batches_by_id.get(batch_id)
        if batch is None:
            raise ValueError(f"No batch {batch_id}")

        # Prevent deleting a batch that still has claimed stock, since that would
        # silently drop customer reservations.
        if batch.reserved > 0:
            raise ValueError(
                f"Batch {batch_id} has reservations, cancel them first")

        # Reduce the total available units for this SKU when the batch is removed.
        self.available_by_sku[batch.sku] -= batch.available

        # Remove the batch from active storage. Its heap entries remain stale but
        # are ignored later during heap cleanup.
        del self.batches_by_id[batch_id]
        return batch
    def top_k_expiring(self, k: int, today: date) -> list[Batch]:
        """Return the k earliest-expiring sellable batches store-wide.

        Read-only: does not modify inventory or heaps.
        Ties are broken by batch ID.
        Time complexity: O(n log n).
        """

        if not isinstance(k, int) or isinstance(k, bool) or k < 0:
            raise ValueError("k must be a non-negative integer")

        # Filter eligible batches without changing inventory state.
        eligible = [
            batch
            for batch in self.batches_by_id.values()
            if batch.sell_by > today
            and not batch.expired
            and batch.quantity - batch.reserved > 0
        ]

        # Sort by earliest expiration, then batch ID.
        eligible.sort(key=lambda batch: (batch.expiry, batch.batch_id))

        # Return only the first k batches.
        return eligible[:k]


# testing inventory operations
if __name__ == "__main__":
    """Basic smoke test to confirm the module loads and batch deletion works."""
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