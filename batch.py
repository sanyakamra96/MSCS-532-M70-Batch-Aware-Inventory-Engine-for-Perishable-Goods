"""
batch.py - the Batch record and the error type shared by every module.

A Batch is one delivery of one product (SKU) with a single expiration date.
Batches are stored in Inventory.batches_by_id (a Python dict / hash table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

@dataclass(slots=True)
class Batch:
    """One delivery of a product.

    ``slots=True`` keeps every Batch out of an instance dictionary: construction
    is ~20 % faster and each stored batch uses one pointer-sized slot per field
    instead of a dict, which matters because the engine stores one per delivery.

    Attributes
    ----------
    batch_id : unique ID such as "B101" (key in batches_by_id)
    sku      : product identifier such as "milk"
    expiry   : the printed expiration date
    sell_by  : last day the batch may be sold is the day *before* this date;
               sell_by = expiry - buffer (3 days by default)
    quantity : units physically on hand (includes reserved units)
    reserved : units set aside for customer orders, not yet fulfilled
    version  : availability version; when it changes, older heap entries
               for this batch become stale and are skipped (lazy deletion)
    expired  : True once the batch has reached its sell_by date and has been
               removed from sellable stock
    holds    : order_id -> units of this batch reserved by that order
    """

    batch_id: str
    sku: str
    expiry: date
    sell_by: date
    quantity: int
    reserved: int = 0
    version: int = 0
    expired: bool = False
    holds: dict[str, int] = field(default_factory=dict)

    @property
    def available(self) -> int:
        """Sellable units: not reserved and not expired. O(1)."""
        return 0 if self.expired else self.quantity - self.reserved


def check_quantity(quantity: int) -> None:
    """Raise ValueError unless quantity is a positive whole number."""
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError(f"Quantity must be a positive whole number, got {quantity!r}")