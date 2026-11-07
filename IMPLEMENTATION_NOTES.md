# Implementation Notes – Phase 2 Grocery Inventory Prototype

## 1. What we built

| File | Contents |
|---|---|
| `batch.py` | `Batch` dataclass (ID, SKU, expiry, sell-by, quantity, reserved, version, expired flag, `holds`), and `check_quantity` (`ValueError` for invalid quantities) |
| `heap_manager.py` | `HeapManager`: `lots_by_sku` and `expiry_events` heaps, lazy-deletion checks, `pop_due`, and `fefo_allocation` |
| `inventory.py` | `Inventory`: owns inventory state; `insert_batch`, `search_batch`, `delete_batch`, `available`, `process_expired`, and `expire_due` |
| `reservations.py` | `reserve`, `fulfill`, and `cancel_reservation` |

Invalid operations raise the built-in `ValueError`; there is no custom
`InventoryError` class.

### Data structures

- `batches_by_id` – dict, batch ID → `Batch`. O(1) average lookup.
- `lots_by_sku` – dict of min-heaps, keyed `(expiry, batch_id, version)`. Each
  heap supports FEFO allocation for one SKU.
- `expiry_events` – min-heap keyed `(sell_by, batch_id, version)`. Its top is
  the next batch to leave sellable inventory.
- `available_by_sku` – dict, SKU → sellable units.
- `orders` – dict, order ID → `{batch_id: units}`. Each `Batch.holds` stores
  the reverse mapping.
- `_pending_expiry_reports` – reports created by expiration and retained until
  `process_expired` returns them.

### Stale heap entries

`heapq` cannot delete or update an entry. Each entry stores the batch version
when it was pushed. Deleting, expiring, or selling out a batch invalidates old
entries by removing the batch or changing its version. Old entries are skipped
when encountered. Versions come from one global counter, so deleting and
reinserting a batch ID cannot make an old entry appear current.

### Sell-by buffer

`sell_by = expiry − expiry_buffer_days`, with a default buffer of 3 days.
On or after `sell_by` the batch is expired. Dated operations that can report,
reserve, or fulfill stock call `expire_due(today)` first. `process_expired`
also collects any unreported reconciliation events, including ones triggered
by an earlier operation.

### Complexity

Let *m* be the number of entries in the relevant heap, *k* the entries popped
while allocating a reservation, *d* the due expiry entries processed, *r* the
pending reports returned, and *b* the number of batches in an order. Heap
operations take logarithmic time in the size of their heap; stale entries mean
heap size can exceed the number of live batches.

| Operation | Time | Additional space |
|---|---|---|
| `insert_batch` | O(log m) | O(1) record and heap entries |
| `search_batch` | O(1) average | O(1) |
| `delete_batch` | O(1) average; heap entries are invalidated lazily | O(1) |
| `available` | O(1) when nothing is due; O(d log m) for due expirations | O(d) for pending reports |
| `reserve` | O(d log m + k log m), including due expirations | O(d + k) for reports and allocation |
| `fulfill` | O(d log m + b), including due expirations | O(d + b) for reports and expired-batch checks |
| `cancel_reservation` | O(b) | O(1) beyond the returned allocation |
| `process_expired` | O(d log m + r) | O(d + r) for due batches and returned reports |

## 2. Design change: per-product available counter

**Original:** quantities exist only per batch, so calculating how much of a
product is sellable requires visiting every batch of that SKU: O(m).

**Change:** `available_by_sku` keeps a running total. `insert_batch`,
`delete_batch`, `reserve`, `cancel_reservation`, and expiration update it.
`fulfill` leaves it unchanged because the fulfilled units were already
reserved and therefore were not counted as available.

**Why it helps:** The design assumes a read-heavy workload. This makes an
availability lookup O(1) when no batches are due and lets `reserve` reject
insufficient stock before planning a heap allocation.

**Cost:** The counter must stay in sync with individual batches. Reservation
planning checks for disagreement and refuses the reservation if the recorded
available total cannot be satisfied by the heaps. Tests verify totals across
insert, delete, reserve, fulfill, cancel, and expiration.

## 3. Gaps in the Phase 1 design and how we filled them

These are additions, not changes. Phase 1 left them unspecified.

- **Cancellation.** The `orders` ledger and `Batch.holds` record which batches
  supplied an order and allow reserved units to be released.
- **Expired reserved stock.** Expiration produces a reconciliation report.
  `fulfill` refuses orders holding expired stock, and
  `cancel_reservation` releases those units without returning them to sellable
  inventory.
- **Delete.** `delete_batch` refuses to remove a batch while it has
  reservations.
- **Bad input.** Duplicate IDs, non-positive or non-integer quantities,
  negative expiry buffers, and batches already past their sell-by date are
  rejected with `ValueError`.

## 4. Deferred

- Partial fulfillment and orders spanning several SKUs; each order is one SKU
  and is fulfilled whole.
- Restocking or adjusting an existing batch's quantity.
- Saving data to disk or a database; state lives in memory only.
- Benchmarking a read-heavy workload.
- Automatic re-reservation from fresh stock when a reserved batch expires;
  staff act on the reconciliation report.
- CSV/database bulk-import workflows.

## 5. Known weaknesses

- **Fully reserved batches.** A fully reserved, non-expired batch remains in
  `lots_by_sku`. A later reservation may pop and re-push it while looking for
  available stock.
- **Heap growth.** Stale entries for deleted or sold-out batches can remain in
  heaps until they are encountered. Expiration heap entries for those batches
  can remain until their sell-by dates reach the top.
- **Single thread only.** Concurrent calls could break the counters because
  there is no locking.
- **Dates come from the caller.** Dated operations accept `today`, which makes
  testing straightforward, but the code does not reject dates earlier than a
  previous call.
- **Exposed internals.** `search_batch` returns the live `Batch` object, so a
  caller can modify inventory state directly.

## 6. How to run

From the repository folder:

```bash
python demo.py
python -m unittest discover tests -v
python -m pytest -v  # if pytest is installed
```

The current test suite contains 42 tests covering batch operations,
reservations, FEFO order, all-or-nothing rejection, stale heap entries,
expiration reconciliation, cross-product expiration, and a configurable
sell-by buffer.

## Importing data (not implemented)

Supplier deliveries can be read from a CSV with `batch_id`, `sku`, `quantity`,
and `expiry` columns, then passed to `insert_batch` so each row is validated
using the same inventory rules. The current project has no CSV importer,
database, or persistence layer; rejected-row reporting and bulk database
loading would need to be implemented separately.

## Appendix: AI usage

*Edit this to match what your group actually did.*

We used Claude (Anthropic) to:

- explain the Phase 1 design in plain language;
- draft the initial module structure, functions, demo script, and test cases;
- draft these implementation notes.

The group reviewed every function, ran the demo and the full test suite, and
checked the Big-O analysis. Each member can explain any function for the code
walkthrough. All design decisions, including the per-product available
counter, were reviewed and agreed by the group.
