"""Insert, search and delete batches; lots_by_sku and expiry_events contents."""

import unittest

from tests.helpers import d
from inventory import Inventory
from reservations import reserve


class TestInsert(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()

    def test_insert_stores_batch(self):
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.assertIn("B101", self.inv.batches_by_id)
        self.assertEqual(self.inv.available("milk", d(1)), 20)

    def test_insert_pushes_onto_both_heaps(self):
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.assertEqual(self.inv.lots_by_sku["milk"][0][:2], (d(7), "B101"))
        self.assertEqual(self.inv.expiry_events[0][:2], (d(4), "B101"))  # 3-day buffer

    def test_sell_by_uses_three_day_buffer(self):
        b = self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.assertEqual(b.sell_by, d(4))

    def test_duplicate_id_rejected(self):
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        with self.assertRaises(ValueError):
            self.inv.insert_batch("B101", "milk", 5, d(9), today=d(1))

    def test_invalid_quantities_rejected(self):
        for bad in (0, -5, 2.5, True, "10"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.inv.insert_batch("BX", "milk", bad, d(20), today=d(1))
        self.assertNotIn("BX", self.inv.batches_by_id)

    def test_batch_already_past_sell_by_rejected(self):
        # Expires Nov 7, sell-by Nov 4; arriving on Nov 5 is too late.
        with self.assertRaises(ValueError):
            self.inv.insert_batch("B101", "milk", 20, d(7), today=d(5))

    def test_multiple_skus_tracked_separately(self):
        self.inv.insert_batch("B101", "milk", 20, d(10), today=d(1))
        self.inv.insert_batch("Y201", "yogurt", 12, d(12), today=d(1))
        self.assertEqual(self.inv.available("milk", d(1)), 20)
        self.assertEqual(self.inv.available("yogurt", d(1)), 12)
        self.assertEqual(self.inv.available("cheese", d(1)), 0)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.inv.insert_batch("B102", "milk", 30, d(15), today=d(1))

    def test_search_returns_correct_batch(self):
        b = self.inv.search_batch("B101")
        self.assertEqual((b.batch_id, b.sku, b.quantity, b.expiry), ("B101", "milk", 20, d(7)))

    def test_search_nonexistent_returns_none(self):
        self.assertIsNone(self.inv.search_batch("B999"))


class TestDelete(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.inv.insert_batch("B102", "milk", 30, d(15), today=d(1))

    def test_delete_removes_batch_and_stock(self):
        self.inv.delete_batch("B101")
        self.assertIsNone(self.inv.search_batch("B101"))
        self.assertEqual(self.inv.available("milk", d(1)), 30)

    def test_delete_nonexistent_rejected(self):
        with self.assertRaises(ValueError):
            self.inv.delete_batch("B999")

    def test_delete_with_reservations_rejected(self):
        reserve(self.inv, "O1", "milk", 5, d(1))
        with self.assertRaises(ValueError):
            self.inv.delete_batch("B101")
        self.assertIsNotNone(self.inv.search_batch("B101"))

    def test_deleted_batch_skipped_by_fefo(self):
        self.inv.delete_batch("B101")
        self.assertEqual(reserve(self.inv, "O1", "milk", 10, d(1)), {"B102": 10})

    def test_reinsert_same_id_ignores_old_heap_entries(self):
        self.inv.delete_batch("B101")
        self.inv.insert_batch("B101", "milk", 5, d(20), today=d(1))
        # Old entry (expiry Nov 7) is stale; the new B101 expires after B102.
        self.assertEqual(reserve(self.inv, "O1", "milk", 32, d(1)), {"B102": 30, "B101": 2})
        # Old expiry event (Nov 4) must not expire the new B101.
        self.assertEqual(self.inv.process_expired(d(5)), [])
        self.assertFalse(self.inv.search_batch("B101").expired)


if __name__ == "__main__":
    unittest.main()
