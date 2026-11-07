"""
batch.py - the Batch record and the error type shared by every module.

A Batch is one delivery of one product (SKU) with a single expiration date.
Batches are stored in Inventory.batches_by_id (a Python dict / hash table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

@dataclass
class Batch:
    """One delivery of a product.

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
    """

    batch_id: str
    sku: str
    expiry: date
    sell_by: date
    quantity: int
    reserved: int = 0
    version: int = 0