"""
reservations.py - customer order operations: reserve, fulfill, cancel.

Every function takes the Inventory as its first argument and keeps these
consistency rules:
  * reserved never exceeds quantity in any batch
  * reservations are all-or-nothing
  * only non-reserved, non-expired stock can be reserved
  * expired stock is never handed to a customer

Reservation ledger: inventory.orders maps order_id -> {batch_id: units}.
Phase 1 did not say how a cancellation finds the stock it must release; the
ledger answers that, and each Batch.holds keeps the reverse mapping so
expiration can report which orders are affected.
"""

from __future__ import annotations

from datetime import date

from batch import check_quantity
from inventory import Inventory


def reserve(inv: Inventory, order_id: str, sku: str, qty: int,
            today: date) -> dict[str, int]:
    """Set aside `qty` units of `sku` for an order, earliest expiry first (FEFO).

    All-or-nothing: if the full amount is not available, nothing changes and
    ValueError is raised.
    Returns {batch_id: units} showing which batches supply the order.
    O(1) rejection check, then O(k log m) for k batches touched.
    """
    if order_id in inv.orders:
        raise ValueError(f"Order {order_id} already exists")
    check_quantity(qty)
    inv.expire_due(today)
    available = inv.available_by_sku.get(sku, 0)
    if available < qty:
        raise ValueError(f"Only {available} {sku} available, {qty} requested")

    allocation = inv.heaps.fefo_allocation(sku, qty, inv.batches_by_id)
    if allocation is None:                     # counter and batches disagree
        raise ValueError("Inventory counts are inconsistent; reservation refused")

    for batch_id, units in allocation.items():   # commit only after planning succeeds
        batch = inv.batches_by_id[batch_id]
        batch.reserved += units
        batch.holds[order_id] = units
    inv.available_by_sku[sku] -= qty
    inv.orders[order_id] = allocation
    return dict(allocation)


def fulfill(inv: Inventory, order_id: str, today: date) -> dict[str, int]:
    """Hand a reserved order to the customer and deduct it from stock.

    Refuses (changing nothing) if any batch in the order has expired; the
    order must be cancelled and reserved again from good stock.
    Available stock does not change, because reserved units were never
    counted as available.  O(b) for b batches in the order.
    """
    inv.expire_due(today)
    allocation = inv.orders.get(order_id)
    if allocation is None:
        raise ValueError(f"No reservation for order {order_id}")
    expired = [bid for bid in allocation
               if inv.batches_by_id[bid].expired]
    if expired:
        raise ValueError(
            f"Order {order_id} holds expired batch(es) {expired}; cancel and re-reserve")

    for batch_id, units in allocation.items():
        batch = inv.batches_by_id[batch_id]
        batch.quantity -= units
        batch.reserved -= units
        del batch.holds[order_id]
        if batch.quantity == 0:
            batch.version = inv.new_version()
    return inv.orders.pop(order_id)


def cancel_reservation(inv: Inventory, order_id: str) -> dict[str, int]:
    """Release a reservation so its units can be sold again.

    Units from batches that have already expired are released from the
    order but do NOT return to available stock.  O(b) for b batches in the order.
    """
    allocation = inv.orders.pop(order_id, None)
    if allocation is None:
        raise ValueError(f"No reservation for order {order_id}")
    for batch_id, units in allocation.items():
        batch = inv.batches_by_id[batch_id]
        batch.reserved -= units
        del batch.holds[order_id]
        if not batch.expired:
            inv.available_by_sku[batch.sku] += units
    return allocation
