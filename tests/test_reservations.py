"""Reserve, fulfill and cancel."""

import unittest

from tests.helpers import d
from inventory import Inventory
from reservations import cancel_reservation, fulfill, reserve


class ReservationTestCase(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()
        self.inv.insert_batch("B101", "milk", 20, d(7), today=d(1))
        self.inv.insert_batch("B102", "milk", 30, d(15), today=d(1))

    def avail(self, day=1):
        return self.inv.available("milk", d(day))


class TestReserve(ReservationTestCase):
    def test_reserve_decreases_available_by_10(self):
        reserve(self.inv, "O1", "milk", 10, d(1))
        self.assertEqual(self.avail(), 40)

    def test_reserve_uses_earliest_expiry_first(self):
        self.assertEqual(reserve(self.inv, "O1", "milk", 25, d(1)), {"B101": 20, "B102": 5})
        self.assertEqual(self.inv.search_batch("B101").reserved, 20)
        self.assertEqual(self.inv.search_batch("B102").reserved, 5)

    def test_reserve_more_than_available_rejected_and_nothing_changes(self):
        with self.assertRaises(ValueError):
            reserve(self.inv, "O1", "milk", 51, d(1))
        self.assertEqual(self.avail(), 50)
        self.assertEqual(self.inv.search_batch("B101").reserved, 0)
        self.assertNotIn("O1", self.inv.orders)

    def test_reserved_stock_cannot_be_reserved_again(self):
        reserve(self.inv, "O1", "milk", 45, d(1))
        with self.assertRaises(ValueError):
            reserve(self.inv, "O2", "milk", 6, d(1))
        self.assertEqual(reserve(self.inv, "O3", "milk", 5, d(1)), {"B102": 5})
        self.assertEqual(self.avail(), 0)

    def test_reserve_unknown_product_rejected(self):
        with self.assertRaises(ValueError):
            reserve(self.inv, "O1", "cheese", 1, d(1))

    def test_duplicate_order_id_rejected(self):
        reserve(self.inv, "O1", "milk", 1, d(1))
        with self.assertRaises(ValueError):
            reserve(self.inv, "O1", "milk", 1, d(1))

    def test_invalid_quantity_rejected(self):
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                reserve(self.inv, "O1", "milk", bad, d(1))

    def test_reserved_never_exceeds_quantity(self):
        reserve(self.inv, "O1", "milk", 50, d(1))
        for b in self.inv.batches_by_id.values():
            self.assertLessEqual(b.reserved, b.quantity)


class TestFulfill(ReservationTestCase):
    def test_fulfill_deducts_stock(self):
        reserve(self.inv, "O1", "milk", 25, d(1))
        fulfill(self.inv, "O1", d(1))
        self.assertEqual(self.inv.search_batch("B101").quantity, 0)
        self.assertEqual(self.inv.search_batch("B102").quantity, 25)
        self.assertEqual(self.inv.search_batch("B102").reserved, 0)
        self.assertEqual(self.avail(), 25)      # unchanged by fulfilment
        self.assertNotIn("O1", self.inv.orders)

    def test_sold_out_batch_skipped_afterwards(self):
        reserve(self.inv, "O1", "milk", 20, d(1))
        fulfill(self.inv, "O1", d(1))
        self.assertEqual(reserve(self.inv, "O2", "milk", 3, d(1)), {"B102": 3})

    def test_fulfill_unknown_order_rejected(self):
        with self.assertRaises(ValueError):
            fulfill(self.inv, "NOPE", d(1))

    def test_fulfill_twice_rejected(self):
        reserve(self.inv, "O1", "milk", 5, d(1))
        fulfill(self.inv, "O1", d(1))
        with self.assertRaises(ValueError):
            fulfill(self.inv, "O1", d(1))


class TestCancel(ReservationTestCase):
    def test_cancel_releases_reserved_quantity(self):
        reserve(self.inv, "O1", "milk", 10, d(1))
        cancel_reservation(self.inv, "O1")
        self.assertEqual(self.inv.search_batch("B101").reserved, 0)
        self.assertEqual(self.avail(), 50)
        self.assertNotIn("O1", self.inv.orders)

    def test_cancel_unknown_order_rejected(self):
        with self.assertRaises(ValueError):
            cancel_reservation(self.inv, "NOPE")

    def test_cancelled_stock_can_be_reserved_again(self):
        reserve(self.inv, "O1", "milk", 50, d(1))
        cancel_reservation(self.inv, "O1")
        self.assertEqual(reserve(self.inv, "O2", "milk", 20, d(1)), {"B101": 20})


if __name__ == "__main__":
    unittest.main()
