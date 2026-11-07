"""
demo.py - walks through the assignment's milk example.

Run:  python demo.py

Sample scenario for batches of milk.Default sell-by buffer is 3 days, so B101 (expires Nov 7) stops being
sellable on Nov 4, and B102 (expires Nov 15) on Nov 12.
"""

from datetime import date

from inventory import Inventory
from reservations import cancel_reservation, fulfill, reserve


def d(day: int) -> date:
    return date(2026, 11, day)  


def show(day: date, text: str) -> None:
    print(f"{day:%b %d}  {text}")


def main() -> None:
    inv = Inventory(expiry_buffer_days=3)
    nov1, nov7 = d(1), d(7)             # check dates
    print("=== Grocery inventory demo (3-day sell-by buffer) ===\n")

    # 1. Add 20 cartons expiring Nov 7, and 30 expiring Nov 15
    b101 = inv.insert_batch("B101", "milk", 20, expiry=d(7), today=nov1)  # insert batch B101
    b102 = inv.insert_batch("B102", "milk", 30, expiry=d(15), today=nov1)  # insert batch B102
    show(nov1, f"Inserted B101: 20 milk, expires {b101.expiry:%b %d}, sell-by {b101.sell_by:%b %d}")
    show(nov1, f"Inserted B102: 30 milk, expires {b102.expiry:%b %d}, sell-by {b102.sell_by:%b %d}")
    # Additional products for store-wide expiration ranking
    b103 = inv.insert_batch("B103", "bread", 40, expiry=d(10), today=nov1)
    b104 = inv.insert_batch("B104", "eggs", 60, expiry=d(12), today=nov1)
    b105 = inv.insert_batch("B105", "yogurt", 25, expiry=d(9), today=nov1)
    # Additional grocery inventory
    inv.insert_batch("B106", "milk", 50, expiry=d(20), today=nov1)
    inv.insert_batch("B107", "bread", 30, expiry=d(14), today=nov1)
    inv.insert_batch("B108", "eggs", 100, expiry=d(25), today=nov1)
    inv.insert_batch("B109", "cheese", 45, expiry=d(18), today=nov1)
    inv.insert_batch("B110", "butter", 35, expiry=d(22), today=nov1)
    inv.insert_batch("B111", "spinach", 25, expiry=d(8), today=nov1)
    inv.insert_batch("B112", "tomatoes", 80, expiry=d(11), today=nov1)
    inv.insert_batch("B113", "potatoes", 120, expiry=d(28), today=nov1)
    inv.insert_batch("B114", "yogurt", 40, expiry=d(16), today=nov1)
    inv.insert_batch("B115", "apples", 70, expiry=d(24), today=nov1)

    print("\n=== Store-wide inventory ===")

    for batch in inv.batches_by_id.values():
        print(
            f"{batch.batch_id}: "
            f"{batch.sku:10} "
            f"qty={batch.quantity:3} "
            f"expiry={batch.expiry} "
            f"sell_by={batch.sell_by}"
        )
    print("\n=== Top 5 Expiring Batches (Nov 1) ===")

    for batch in inv.top_k_expiring(5, nov1):
        print(
            f"{batch.batch_id}: {batch.sku:10} "
            f"expiry={batch.expiry} "
            f"available={batch.available}"
        )

    # 2. Check available milk -> 50
    show(nov1, f"Available milk: {inv.available('milk', nov1)}")        #check available milk

    # 3. Reserve 10 cartons -> taken from B101 first (FEFO)
    show(nov1, f"Reserved ORD-1 (10 milk) from: {reserve(inv, 'ORD-1', 'milk', 10, nov1)}") # reserve 10 milk for ORD-1

    # 4. Check available milk -> 40
    show(nov1, f"Available milk: {inv.available('milk', nov1)}")        #check available milk on Nov 1

    # Unusual case: all-or-nothing rejection
    try:
        reserve(inv, "ORD-2", "milk", 95, nov1)      # in case of insufficient stock
    except ValueError as e:
        show(nov1, f"ORD-2 (95 milk) rejected: {e}")

    # 5. Process expiration on Nov 7 -> B101 removed, ORD-1 flagged
    report = inv.process_expired(nov7)
    show(nov7, "Processed expiration. Reconciliation report:")
    for item in report:
        print(f"         {item['batch_id']} ({item['sku']}) passed sell-by "  # print expired batch details
              f"{item['sell_by']:%b %d}; affected orders: {item['orders']}")

    # 6. Check available milk -> 30
    show(nov7, f"Available milk: {inv.available('milk', nov7)}")   #check available milk on Nov 7

    # Search, including a batch that does not exist
    b = inv.search_batch("B101")  # search for batch B101
    if b is None:
        raise RuntimeError("Expected batch B101 to remain in inventory")
    show(nov7, f"Search B101: qty={b.quantity}, reserved={b.reserved}, "
               f"available={b.available}, expired={b.expired}")       #availability of batch B101
    show(nov7, f"Search B999: {inv.search_batch('B999')}")  # search for batch B999

    # ORD-1 holds expired milk, so it cannot be fulfilled; cancel and re-reserve
    try:
        fulfill(inv, "ORD-1", nov7)
    except ValueError as e:
        show(nov7, f"Fulfill ORD-1 blocked: {e}")
    cancel_reservation(inv, "ORD-1")                # cancel reservation for ORD-1 if it cannot be fulfilled
    show(nov7, f"Cancelled ORD-1. Available milk: {inv.available('milk', nov7)} "
               "(expired units do not come back)")
    show(nov7, f"Reserved ORD-3 (10 milk) from: {reserve(inv, 'ORD-3', 'milk', 10, nov7)}") # reserve 10 milk for ORD-3
    show(nov7, f"Fulfilled ORD-3: {fulfill(inv, 'ORD-3', nov7)}")  # fulfill ORD-3
    show(nov7, f"Available milk: {inv.available('milk', nov7)}, "  # check available milk on Nov 7
               f"B102 on hand: {b102.quantity}")

    # Delete the expired batch once it has been physically removed
    inv.delete_batch("B101")  # delete batch B101 due to expiration
    show(nov7, f"Deleted B101. Search B101: {inv.search_batch('B101')}")  # confirm batch B101 is deleted


if __name__ == "__main__":
    main()
