"""
demo.py - walks through the assignment's milk example.

Run:  python demo.py

Default sell-by buffer is 3 days, so B101 (expires Nov 7) stops being
sellable on Nov 4, and B102 (expires Nov 15) on Nov 12.
"""

from datetime import date

from inventory import Inventory


def d(day: int) -> date:
    return date(2026, 11, day)


def show(day: date, text: str) -> None:
    print(f"{day:%b %d}  {text}")


def main() -> None:
    inv = Inventory(expiry_buffer_days=3)
    nov1 = d(1)
    print("=== Grocery inventory demo (3-day sell-by buffer) ===\n")

    # Add 20 cartons expiring Nov 7, and 30 expiring Nov 15.
    b101 = inv.insert_batch("B101", "milk", 20, expiry=d(7), today=nov1)
    b102 = inv.insert_batch("B102", "milk", 30, expiry=d(15), today=nov1)
    show(nov1, f"Inserted B101: 20 milk, expires {b101.expiry:%b %d}, sell-by {b101.sell_by:%b %d}")
    show(nov1, f"Inserted B102: 30 milk, expires {b102.expiry:%b %d}, sell-by {b102.sell_by:%b %d}")

    show(nov1, f"Available milk: {inv.available_by_sku['milk']}")

    # Preview a FEFO pick without changing inventory.
    pick = inv.heaps.fefo_allocation("milk", 25, inv.batches_by_id)
    show(nov1, f"FEFO pick plan for 25 milk (preview only): {pick}")
    show(nov1, f"Available milk after preview: {inv.available_by_sku['milk']}")

    b = inv.search_batch("B101")
    if b is not None:
        show(nov1, f"Search B101: qty={b.quantity}, available={b.available}")
    show(nov1, f"Search B999: {inv.search_batch('B999')}")

    # Delete a batch and show the updated stock total.
    inv.delete_batch("B101")
    show(nov1, f"Deleted B101. Available milk: {inv.available_by_sku['milk']}")
    show(nov1, f"Search B101: {inv.search_batch('B101')}")


if __name__ == "__main__":
    main()
