
import unittest
from datetime import date

from inventory import Inventory
from reservations import reserve


class TestTopKExpiring(unittest.TestCase):

    def setUp(self):
        self.today = date(2026, 11, 1)
        self.inv = Inventory(expiry_buffer_days=3)

        self.inv.insert_batch("B101", "milk", 20, date(2026, 11, 10), self.today)
        self.inv.insert_batch("B102", "bread", 30, date(2026, 11, 12), self.today)
        self.inv.insert_batch("B103", "eggs", 40, date(2026, 11, 10), self.today)
        self.inv.insert_batch("B104", "yogurt", 15, date(2026, 11, 15), self.today)

    def test_k_zero(self):
        self.assertEqual(self.inv.top_k_expiring(0, self.today), [])

    def test_k_larger_than_inventory(self):
        result = self.inv.top_k_expiring(100, self.today)
        self.assertEqual(len(result), 4)

    def test_earliest_expiring_order(self):
        result = self.inv.top_k_expiring(3, self.today)
        self.assertEqual(
            [batch.batch_id for batch in result],
            ["B101", "B103", "B102"]
        )

    def test_equal_expiry_tiebreak(self):
        result = self.inv.top_k_expiring(2, self.today)
        self.assertEqual(
            [batch.batch_id for batch in result],
            ["B101", "B103"]
        )

    def test_fully_reserved_batch_excluded(self):
        reserve(self.inv, "ORD-1", "milk", 20, self.today)

        result = self.inv.top_k_expiring(3, self.today)
        self.assertNotIn("B101", [batch.batch_id for batch in result])

    def test_expired_batch_excluded_and_read_only(self):
        later = date(2026, 11, 8)

        before_batches = {
            bid: (batch.quantity, batch.reserved, batch.expired, batch.version)
            for bid, batch in self.inv.batches_by_id.items()
        }
        before_heap = list(self.inv.expiry_events)
        before_sku_heaps = {
            sku: list(heap)
            for sku, heap in self.inv.lots_by_sku.items()
        }
        before_available = dict(self.inv.available_by_sku)

        result = self.inv.top_k_expiring(10, later)

        # B101 and B103 stop being sellable on Nov 7.
        self.assertEqual(
            [batch.batch_id for batch in result],
            ["B102", "B104"]
        )

        after_batches = {
            bid: (batch.quantity, batch.reserved, batch.expired, batch.version)
            for bid, batch in self.inv.batches_by_id.items()
        }

        self.assertEqual(before_batches, after_batches)
        self.assertEqual(before_heap, self.inv.expiry_events)
        self.assertEqual(before_sku_heaps, self.inv.lots_by_sku)
        self.assertEqual(before_available, self.inv.available_by_sku)


if __name__ == "__main__":
    unittest.main()
