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

### 2.3 `Inventory.search_batch` — `inventory.py:193`

This one is already at the floor: it is a single `dict.get` on a hash table, O(1)
average. Measured 0.10 µs per call (hit) and 0.09 µs (miss); a raw `d[key]` hit is
0.07 µs, so there is no algorithm left to change.

What was done instead is to remove the only remaining overhead around the lookup:

- `Inventory` now declares `__slots__` (`inventory.py:46`), so `self.batches_by_id` is a
  slot read instead of an instance-dictionary lookup (measured 86.9 ns vs 103.8 ns for
  the attribute+`get` pair on a hit).
- Variants that were *rejected*: `try: d[key]` beats `.get` on hits (70.8 ns) but costs
  315.7 ns on a miss, so with the 50 %-miss workload it is worse; caching the bound
  `d.get` method in `__init__` gains ~4 ns but silently breaks if the dict attribute is
  ever reassigned.

Measured effect: 1.01× on hits, 1.03× on misses — i.e. inside noise. Reported as such
rather than claimed as a win.

### 2.4 Supporting change: `Batch` uses `slots=True` — `batch.py:13`

`Batch` is created once per delivery and there is one per stored batch, so it is the
single hottest constructor in the system: it was **0.76 µs of the 3.7 µs** `insert_batch`.

`@dataclass(slots=True)` removes the per-instance `__dict__`:

- construction 0.764 µs → **0.594 µs** (−22 %)
- memory after building 2 000 batches 1.04 MB → **0.94 MB**; peak 1.15 MB → 1.06 MB
- all fields (`batch_id`, `sku`, `expiry`, `sell_by`, `quantity`, `reserved`, `version`,
  `expired`, `holds`) and the `available` property are unchanged; `holds` keeps its
  `default_factory=dict`.

This is why a few untargeted operations (`fulfill`, `cancel_reservation`, the churn
loop) also got slightly faster.

---

## 3. How the numbers were produced

Two independent measurements, both **old vs new in the same session** (cross-session
drift on this machine is ±15 %, which is why the harness is re-run against the `HEAD`
copy rather than compared to the older `BASELINE.md`):

1. **Workload level — `profiling/profile_baseline.py`**, unchanged since the baseline.
   Three interleaved rounds: old → new → old → new → old → new, median per workload.
   The "old" copy is `git show HEAD:{batch,heap_manager,inventory,reservations}.py` in a
   temporary directory, run with the same harness (`--timing`).
2. **Function level — tight-loop A/B**, 3 interleaved rounds, median, pre-built data and
   **no string formatting inside the measured body** (the workload harness builds an
   f-string per search call, which dominates the 0.5 µs figure there).

### 3.1 Function-level A/B (most reliable for the three targets)

| workload | before | after | change |
|---|---:|---:|---:|
| `insert_batch` | 2.141 µs | **1.881 µs** | **1.14×** |
| `search_batch` (hit) | 0.105 µs | 0.104 µs | 1.01× |
| `search_batch` (miss) | 0.096 µs | 0.093 µs | 1.03× |
| `top_k_expiring(1)` | 1 224.41 µs | **343.64 µs** | **3.56×** |
| `top_k_expiring(10)` | 1 231.24 µs | **425.04 µs** | **2.90×** |
| `top_k_expiring(100)` | 1 196.63 µs | **724.43 µs** | **1.65×** |
| `top_k_expiring(500)` | 1 190.04 µs | 1 647.01 µs | **0.72× (slower)** |
| `top_k_expiring(2000)` | 1 273.59 µs | 1 243.58 µs | 1.02× |

### 3.2 `top_k_expiring` scaling (2 000-batch dataset, µs per call)

| store size | k=1 before → after | k=10 before → after | k=100 before → after |
|---:|---|---|---|
| 250 | 109.5 → **43.8** (2.5×) | 109.4 → **63.6** (1.7×) | 109.6 → **101.0** (1.1×) |
| 500 | 246.3 → **88.2** (2.8×) | 246.1 → **115.4** (2.1×) | 246.4 → **228.1** (1.1×) |
| 1 000 | 547.7 → **177.6** (3.1×) | 548.1 → **216.5** (2.5×) | 549.4 → **460.6** (1.2×) |
| 2 000 | 1 178.6 → **356.2** (3.3×) | 1 178.6 → **407.9** (2.9×) | 1 178.8 → **717.6** (1.6×) |
| 4 000 | 2 514.5 → **942.3** (2.7×) | 2 520.2 → **1 022.5** (2.5×) | 2 514.7 → **1 400.8** (1.8×) |

The before curve is flat in `k` (a full sort ignores `k`); the after curve now depends
on both `n` and `k`, which is the point of the change.

### 3.3 cProfile, same mixed workload

| | before | after |
|---|---:|---:|
| total | 0.217 s, 301 918 calls | **0.093 s**, 301 918 calls |
| `top_k_expiring` cumulative | 0.161 s (74.2 %) | **0.038 s** (40.9 %) |
| `list.sort` | 0.143 s self | *gone* |
| `inventory.py:217(<lambda>)` | 0.023 s, 200 000 calls | *gone* |
| `heapq.nsmallest` | — | 0.015 s, 100 calls |
| `insert_batch` | 0.013 s, 2 000 calls | 0.010 s |

---

## 4. Trade-offs and known limits

**Large `k` is not improved — and mid-range `k` is slower.** `nsmallest` only wins while
`k` is small relative to the number of eligible batches. Measured crossover on this
dataset is around `k ≈ n/8`; beyond it the heap bookkeeping costs more than one plain
sort (0.72× at `k = 500` of 2 000, i.e. 8× slower than the 3× win at small `k`). A
`if k * 8 > len(candidates): candidates.sort()` fallback was implemented, measured to
restore parity (1.15× at `k = 500`, 1.01× at `k = 2000`) and then **removed on request**,
so the shipped function is a single path. If large-`k` callers matter, that four-line
guard is what to add back:

```python
if k * 8 > len(candidates):
    candidates.sort()
    return [b for _, _, b in candidates[:k]]
```

**`search_batch` has no headroom.** 0.10 µs is a dict lookup plus a method call.

**`insert_batch` is bounded by its two `heappush` calls** (0.13 µs each) and by `Batch`
construction; both are required by the design (per-SKU FEFO heap + store-wide expiry
heap).

**Untouched hot spots** (identified in `BASELINE.md` §7 but outside this task):
`Inventory.expire_due` / `HeapManager.pop_due` still cost 0.21–0.24 µs on every dated
read, and `HeapManager.fefo_allocation` still re-pushes inspected entries.

---

## 5. Verification

| check | result |
|---|---|
| `python3 -m unittest discover tests` | **48 tests OK** (includes the `top_k` read-only and tie-break tests) |
| `top_k_expiring` output, 35 (k, date) combinations incl. `k=0`, `k > n`, expired and fully-reserved batches | **identical batch IDs and order** before vs after |
| inventory state after a mixed reserve/fulfill/cancel/expire/delete workload (batches, heaps, `available_by_sku`, `orders`, pending reports) | **identical** |
| exception type + message for duplicate ID, zero, bool, float, past sell-by, `k=-1`, `k=True`, `k=1.5` | **identical** (8/8) |
| `search_batch` hits and misses | **identical** |
| `python3 demo.py` output | **byte-identical** (46 lines, empty `diff`) |
| read-only invariant of `top_k_expiring` (heaps, batches, counters unchanged) | **holds** |
| `Inventory.__slots__` / `Batch(slots=True)` vs project code | no code sets undeclared attributes on either class |

Reproduce:

```bash
python3 -m unittest discover tests
python3 profiling/profile_baseline.py --timing      # after
python3 demo.py
```

The A/B runs used throwaway copies of the `HEAD` modules
(`git show HEAD:<file>` into a temp dir) and a temporary benchmark script; only
`inventory.py` and `batch.py` changed in the repository.
