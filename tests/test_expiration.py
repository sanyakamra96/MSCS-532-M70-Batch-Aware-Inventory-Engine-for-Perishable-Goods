"""Expiration with the 3-day sell-by buffer, reconciliation, and the store-wide heap."""

import unittest

from tests.helpers import d
from inventory import Inventory
from reservations import cancel_reservation, fulfill, reserve


class TestExpiration(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()                         # 3-day buffer
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))   # sell-by Nov 4
        self.inv.insert_batch("B102", "milk", 30, d(15), today=d(1))  # sell-by Nov 12

    def test_still_sellable_the_day_before_sell_by(self):
        self.assertEqual(self.inv.process_expired(d(3)), [])
        self.assertEqual(self.inv.search_batch("B101").available, 20)
        self.assertEqual(self.inv.available("milk", d(3)), 50)

    def test_expired_batch_sellable_becomes_zero_three_days_before_expiry(self):
        self.inv.process_expired(d(4))                 # Nov 7 - 3 days
        b = self.inv.search_batch("B101")
        self.assertTrue(b.expired)
        self.assertEqual(b.available, 0)
        self.assertEqual(b.quantity, 20)               # still physically on hand
        self.assertEqual(self.inv.available("milk", d(4)), 30)

    def test_assignment_demo_numbers(self):
        self.assertEqual(self.inv.available("milk", d(1)), 50)
        reserve(self.inv, "O1", "milk", 10, d(1))
        self.assertEqual(self.inv.available("milk", d(1)), 40)
        self.inv.process_expired(d(7))
        self.assertEqual(self.inv.available("milk", d(7)), 30)

    def test_available_expires_automatically(self):
        # No explicit process_expired() call: reads still never count expired stock.
        self.assertEqual(self.inv.available("milk", d(5)), 30)

    def test_expired_stock_cannot_be_reserved(self):
        with self.assertRaises(ValueError):
            reserve(self.inv, "O1", "milk", 31, d(5))
        self.assertEqual(reserve(self.inv, "O2", "milk", 30, d(5)), {"B102": 30})

    def test_reconciliation_reports_reserved_expired_batch(self):
        reserve(self.inv, "O1", "milk", 25, d(1))      # B101:20, B102:5
        report = self.inv.process_expired(d(4))
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["batch_id"], "B101")
        self.assertEqual(report[0]["orders"], {"O1": 20})
        self.assertEqual(self.inv.process_expired(d(4)), [])   # reported once

    def test_reconciliation_kept_when_another_operation_expires_batch(self):
        reserve(self.inv, "O1", "milk", 5, d(1))
        self.inv.available("milk", d(5))               # triggers expiration
        report = self.inv.process_expired(d(5))
        self.assertEqual([r["batch_id"] for r in report], ["B101"])

    def test_fulfill_blocked_when_order_holds_expired_stock(self):
        reserve(self.inv, "O1", "milk", 10, d(1))
        with self.assertRaises(ValueError):
            fulfill(self.inv, "O1", d(4))
        self.assertEqual(self.inv.search_batch("B101").quantity, 20)  # nothing deducted

    def test_cancel_after_expiry_does_not_restore_expired_units(self):
        reserve(self.inv, "O1", "milk", 25, d(1))      # B101:20, B102:5
        self.inv.process_expired(d(4))
        cancel_reservation(self.inv, "O1")
        self.assertEqual(self.inv.available("milk", d(4)), 30)       # only B102's 5 return
        self.assertEqual(self.inv.search_batch("B101").reserved, 0)

    def test_store_wide_heap_expires_across_products_in_order(self):
        self.inv.insert_batch("Y201", "yogurt", 12, d(9), today=d(1))   # sell-by Nov 6
        self.inv.insert_batch("C301", "cheese", 8, d(20), today=d(1))   # sell-by Nov 17
        self.inv.process_expired(d(6))
        self.assertTrue(self.inv.search_batch("B101").expired)
        self.assertTrue(self.inv.search_batch("Y201").expired)
        self.assertFalse(self.inv.search_batch("B102").expired)
        self.assertFalse(self.inv.search_batch("C301").expired)
        self.assertEqual(self.inv.expiry_events[0][1], "B102")          # next due

    def test_sold_out_batch_not_reported_at_expiry(self):
        reserve(self.inv, "O1", "milk", 20, d(1))
        fulfill(self.inv, "O1", d(1))
        self.assertEqual(self.inv.process_expired(d(4)), [])

    def test_buffer_is_configurable(self):
        inv = Inventory(expiry_buffer_days=0)
        inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.assertEqual(inv.available("milk", d(6)), 20)
        self.assertEqual(inv.available("milk", d(7)), 0)

    def test_negative_buffer_rejected(self):
        with self.assertRaises(ValueError):
            Inventory(expiry_buffer_days=-1)


if __name__ == "__main__":
    unittest.main()
