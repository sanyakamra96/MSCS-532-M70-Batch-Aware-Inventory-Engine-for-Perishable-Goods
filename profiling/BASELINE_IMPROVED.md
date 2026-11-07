# Optimized Baseline — `top_k_expiring`, `insert_batch`, `search_batch`

**Status:** optimizations applied to `inventory.py` and `batch.py`. This file is the
"after" record; `profiling/BASELINE.md` stays as the untouched "before" record.
The code changes are **uncommitted** in the working tree.

- Code under test (before): git `1ae9fe6` ("the baseline profile"), extracted with
  `git show HEAD:<file>`. For `batch.py`, `inventory.py`, `heap_manager.py`,
  `reservations.py`, `demo.py` and the tests this commit is byte-identical to the
  original baseline revision `bb95827` — it only added `.gitignore`, `profiling/BASELINE.md`,
  `profiling/profile_baseline.py` and dropped the tracked `.pyc` files.
- Code under test (after): working tree (`batch.py`, `inventory.py`)
- Python 3.14.7 (CPython), Linux 6.18.52 x86_64, 12 logical CPUs
- Reference dataset: unchanged from `profiling/BASELINE.md` §3 — 2 000 batches, 8 SKUs,
  59 000 units, base date `2026-11-01`, 3-day sell-by buffer

---

## 1. Result summary

| workload | before | after | change |
|---|---:|---:|---:|
| `top_k_expiring(10)` | 1 252.42 µs | **414.64 µs** | **3.02× faster** |
| `top_k_expiring(2000)` | 1 200.30 µs | 1 209.43 µs | 0.99× (unchanged) |
| `insert_batch` | 4.38 µs | **3.70 µs** | **1.18× faster** |
| `search_batch` | 0.53 µs | 0.54 µs | 0.99× (at its floor) |
| churn loop (insert+reserve+fulfill+delete+expire) | 9.49 µs | **8.73 µs** | 1.09× faster |
| mixed cProfile workload, total time | 0.217 s | **0.093 s** | **2.33× faster** |
| share of time inside `top_k_expiring` | 74.2 % | **40.9 %** | — |
| memory after building 2 000 batches | 1.04 MB | **0.94 MB** | −10 % |
| peak traced memory (build + 5 000 churn cycles) | 1.15 MB | **1.06 MB** | −8 % |

Side effects on operations that were not targeted (all improvements, from the same
`Batch`/`Inventory` slot change): `fulfill` 1.10×, `cancel_reservation` 1.09×.

Everything else is unchanged within noise: `available` 1.01×, `reserve` 1.03×,
`process_expired` 1.03×, `delete_batch` 1.02×, `expire_due` 0.99×,
`reserve behind 100 fully-reserved` 1.02×.

---

## 2. What was optimized (and why)

### 2.1 `Inventory.top_k_expiring` — `inventory.py:224`

**Before** — full materialization + full sort + slice:

```python
eligible = [batch for batch in self.batches_by_id.values()
            if batch.sell_by > today and not batch.expired
            and batch.quantity - batch.reserved > 0]
eligible.sort(key=lambda batch: (batch.expiry, batch.batch_id))   # O(n log n)
return eligible[:k]
```

**After** — bounded selection, no sort key:

```python
return [batch for _, _, batch in nsmallest(
    k,
    [(batch.expiry, batch.batch_id, batch)
     for batch in self.batches_by_id.values()
     if batch.sell_by > today
     and not batch.expired
     and batch.quantity > batch.reserved],
)]
```

Three separate wins, in order of size:

1. **Algorithm:** `heapq.nsmallest` keeps a max-heap of at most `k` candidates, so the
   cost drops from O(n log n) to **O(n log k)** and one full sort of 2 000 batches
   disappears.
2. **No Python callback:** the old code passed `key=lambda ...`, so Python called that
   lambda **200 000 times** per 100 queries (10.5 % of the whole profile). The new code
   compares `(expiry, batch_id, batch)` tuples at C speed. Batch IDs are unique, so the
   `Batch` element never participates in a comparison.
3. **Cheaper predicate:** `batch.quantity > batch.reserved` replaces
   `batch.quantity - batch.reserved > 0` (no temporary int per batch).

Semantics are unchanged: same eligibility rule (`sell_by > today`, not expired,
sellable units > 0), same ordering (ascending `expiry`, ties by `batch_id`), same
`k` validation (`int`, not `bool`, `>= 0`), `k == 0` short-circuit, returns fewer than
`k` when fewer qualify, and still **read-only** — the heaps, batch records and
`available_by_sku` are never touched.

Remaining floor: the eligibility scan itself is O(n) with ~6 attribute reads per batch
(measured ≈170 µs at n = 2 000). Removing it would need a maintained sorted index that
every mutation must invalidate — deliberately not attempted, because `search_batch`
returns a mutable `Batch` (a documented limitation) and a stale index would return
wrong results rather than just stale counts.

### 2.2 `Inventory.insert_batch` — `inventory.py:103`

**Before** — four separate calls into other objects per insert: `check_quantity()`,
`self.new_version()`, `HeapManager.add_batch()` (which did a `setdefault` plus two
`heapq.heappush`), and the availability `dict.get`.

**After:**

| change | reason |
|---|---|
| local aliases `batches`, `heaps`, `available` | one fewer attribute lookup per access on the hot path |
| `next(self._versions)` instead of `self.new_version()` | skips a Python call frame; the counter is the same global one, so versions still never repeat |
| heap entries pushed inline (`heappush(lot, …)`, `heappush(heaps.expiry_events, …)`) with a `get`/`if` instead of `setdefault` | saves a call frame and a `setdefault` per insert; entry tuples are byte-identical to `HeapManager.add_batch`'s |
| `Batch` dataclass now `slots=True` (see 2.4) | construction drops from 0.76 µs to 0.59 µs |

`HeapManager.add_batch` is kept and still builds the same `(date, batch_id, version)`
tuples; it is simply no longer on the per-insert critical path.

Deliberately **not** changed: `check_quantity()` is still called (0.145 µs) instead of
having its validation copied into `insert_batch`. Duplicating quantity rules in two
places is a correctness risk that is not worth ~4 % of an insert, and `reservations.py`
uses the same helper.