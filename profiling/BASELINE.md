# Performance Baseline — Batch-Aware Inventory Engine

**Purpose:** measure the project *as it is*, before any optimization, so that the next
phase has a reference point. Everything below was produced by
`profiling/profile_baseline.py`, which imports the project modules read-only and
never modifies them.

**Status: BASELINE ONLY — no optimization applied, no source file changed.**

---

## 1. Snapshot of the code under measurement

| Item | Value |
|---|---|
| Git revision | `bb9582711e95bbc90088f1e85a46bdce96770bcf` (`bb95827` — "Add Phase 3 top-k baseline and correctness tests") |
| Working tree at capture | No tracked source file modified (only pre-existing `__pycache__/*.pyc` churn) |
| Python | 3.14.7 (CPython), GCC 15.3.0 |
| OS / CPU | Linux 6.18.52 x86_64, glibc 2.42, 12 logical CPUs |
| Test suite before profiling | `python3 -m unittest discover tests` → **48 tests, OK** (0.002 s) |
| Modules under test | `batch.py`, `heap_manager.py`, `inventory.py`, `reservations.py` (incl. `Inventory.top_k_expiring`, `inventory.py:196`) |

---

## 2. How to reproduce

```bash
# everything (timing + cProfile + memory), writes profiling/baseline.json
python3 profiling/profile_baseline.py --json profiling/baseline.json

# individual sections
python3 profiling/profile_baseline.py --timing
python3 profiling/profile_baseline.py --scaling
python3 profiling/profile_baseline.py --profile
python3 profiling/profile_baseline.py --memory

# inspect the saved C-profiler stats interactively
python3 -c "import pstats; pstats.Stats('profiling/baseline.prof').sort_stats('tottime').print_stats(25)"

# real code path, end to end
python3 -m cProfile -s tottime demo.py > profiling/demo_profile.txt
```

Artifacts in this folder:

| File | Contents |
|---|---|
| `profile_baseline.py` | the harness (dataset, workloads, cProfile/tracemalloc drivers) |
| `baseline.json` | machine-readable results of the full run |
| `baseline_run.txt` | raw stdout of the full run |
| `baseline.prof` | `cProfile` binary stats (`pstats` readable) |
| `baseline_profile.txt` | text dump, sorted by `tottime` and by `cumulative` |
| `demo_profile.txt` | `cProfile` of `python3 demo.py` |

---

## 3. The reference ("common") dataset

Defined in `build_store()`; fully deterministic (no RNG, no wall-clock dependency),
so the same numbers are reproducible on any machine:

| Property | Value |
|---|---|
| Batches | **2 000** deliveries |
| SKUs | 8 (`milk, eggs, bread, yogurt, cheese, juice, butter, cream`) → 250 batches/SKU |
| Batch quantity | `10 + (i * 13) % 40` → 10–49 units |
| Expiry | `base + (4 + (i * 7) % 90)` days → spread over 90 days |
| Base business date | `2026-11-01` |
| Sell-by buffer | 3 days (project default) |
| Total tracked units | 59 000 exactly |

Measurement method: each workload is run **5 times**, each repeat gets a freshly
built store (setup cost excluded from the timing), and the **median** is reported.

---

## 4. Wall-clock baseline

| workload | ops measured | median total | per op | throughput |
|---|---:|---:|---:|---:|
| `insert_batch` | 2 000 | 7.426 ms | **3.71 µs** | 269 333/s |
| `available` | 20 000 | 7.404 ms | **0.37 µs** | 2 701 402/s |
| `search_batch` | 20 000 (50 % misses) | 9.381 ms | **0.47 µs** | 2 132 013/s |
| `reserve` (qty 5) | 500 | 1.899 ms | **3.80 µs** | 263 348/s |
| `fulfill` | 500 | 0.701 ms | **1.40 µs** | 713 291/s |
| `cancel_reservation` | 500 | 0.488 ms | **0.98 µs** | 1 023 774/s |
| `process_expired` (all 2 000 due) | 2 000 | 3.337 ms | **1.67 µs** | 599 330/s |
| `delete_batch` | 500 | 0.190 ms | **0.38 µs** | 2 631 025/s |
| `expire_due` (nothing due) | 20 000 | 4.120 ms | **0.21 µs** | 4 854 302/s |
| `reserve` behind 100 fully-reserved batches | 1 | 0.007 ms | **7.28 µs** | 137 269/s |
| **`top_k_expiring(10)`** | 200 | **205.516 ms** | **1 027.58 µs** | **973/s** |
| **`top_k_expiring(2000)`** | 50 | **51.411 ms** | **1 028.22 µs** | **973/s** |
| churn (insert+reserve+fulfill+delete+expire) | 2 000 cycles | 16.643 ms | 8.32 µs | 120 174/s |

Session-to-session stability: the ranking and ratios are stable across runs, but
absolute per-operation figures drifted by up to ~15 % on this shared machine
(e.g. `insert_batch` measured 3.53–4.11 µs across sessions), while the top-k
measurement stayed within 0.5 % (1 020–1 028 µs). Treat §4 as one session's record and
only compare numbers produced by the same harness on the same machine.

### 4.1 `top_k_expiring` scaling

Median per call, store freshly built per size:

| store size | k = 1 | k = 10 | k = 100 |
|---:|---:|---:|---:|
| 250 batches | 94.7 µs | 94.6 µs | 95.1 µs |
| 500 | 213.4 µs | 212.6 µs | 211.8 µs |
| 1 000 | 475.1 µs | 473.7 µs | 475.6 µs |
| 2 000 | 1 020.7 µs | 1 020.4 µs | 1 020.2 µs |
| 4 000 | 2 189.4 µs | 2 151.8 µs | 2 152.6 µs |

Two facts worth keeping for the next phase:

1. **Linear in store size** (≈ 0.54 µs per stored batch), i.e. O(n) scan + O(n log n) sort.
2. **Completely insensitive to `k`.** Asking for 1 batch costs the same as asking for
   100. A correct top-k should be near-flat and roughly independent of n.

---

## 5. cProfile results (C profiler)

Mixed read/write workload (`profile_workload()`): 2 000 inserts, 6 000 availability
reads, 6 000 point lookups, 100 top-k queries, 400 reserve/fulfill pairs,
300 reserve/cancel pairs, one mass expiration, 300 deletions.

```
301918 function calls in 0.190 seconds
```

### Sorted by `tottime` (self time), top entries

| ncalls | tottime | cumtime | function |
|---:|---:|---:|---|
| 100 | **0.105** | 0.124 | `{method 'sort' of 'list' objects}` ← inside `top_k_expiring` |
| 200 000 | 0.020 | 0.020 | `inventory.py:217(<lambda>)` ← sort key |
| 100 | 0.016 | **0.140** | `inventory.py:196(top_k_expiring)` |
| 7 101 | 0.005 | 0.012 | `inventory.py:128(expire_due)` |
| 2 000 | 0.004 | 0.011 | `inventory.py:88(insert_batch)` |
| 19 747 | 0.003 | 0.003 | `{method 'get' of 'dict' objects}` |
| 7 101 | 0.003 | 0.006 | `heap_manager.py:73(pop_due)` |
| 6 000 | 0.003 | 0.007 | `inventory.py:121(available)` |
| 2 878 | 0.002 | 0.002 | `{built-in method _heapq.heappop}` |
| 700 | 0.002 | 0.007 | `reservations.py:25(reserve)` |
| 700 | 0.002 | 0.004 | `heap_manager.py:31(fefo_allocation)` |
| 4 769 | 0.002 | 0.002 | `{built-in method _heapq.heappush}` |
| 6 000 | 0.001 | 0.002 | `inventory.py:165(search_batch)` |

### Sorted by `cumulative`, top entries

| ncalls | tottime | cumtime | % of 0.190 s | function |
|---:|---:|---:|---:|---|
| 100 | 0.016 | **0.140** | **73.7 %** | `inventory.py:196(top_k_expiring)` |
| 100 | 0.105 | 0.124 | 65.3 % | `list.sort` |
| 200 000 | 0.020 | 0.020 | 10.5 % | `inventory.py:217(<lambda>)` |
| 1 | 0.004 | 0.015 | 7.9 % | `build_store` (harness) |
| 7 101 | 0.005 | 0.012 | 6.3 % | `inventory.py:128(expire_due)` |
| 2 000 | 0.004 | 0.011 | 5.8 % | `inventory.py:88(insert_batch)` |
| 6 000 | 0.003 | 0.007 | 3.7 % | `inventory.py:121(available)` |
| 700 | 0.002 | 0.007 | 3.7 % | `reservations.py:25(reserve)` |
| 7 101 | 0.003 | 0.006 | 3.2 % | `heap_manager.py:73(pop_due)` |
| 700 | 0.002 | 0.004 | 2.1 % | `heap_manager.py:31(fefo_allocation)` |

> Absolute per-call numbers in a profiled run are inflated ~2–3× by the profiler;
> use §4 for the true costs and §5 only for **shares of total time**.

### `demo.py` end to end

`5746 function calls in 0.008 s`, of which ~0.003 s is module import and ~0.001 s is
`demo.main` (15-batch store). The demo is too small to reveal anything; it is recorded
only to confirm the normal code path is covered by the harness.

---

## 6. Memory / heap accounting

`tracemalloc` + explicit counting of live records against heap entries:

| phase | live batches | `expiry_events` entries | `lots_by_sku` entries |
|---|---:|---:|---:|
| after building 2 000 batches | 2 000 | 2 000 | 2 000 |
| after deleting 1 000 batches | 1 000 | **2 000** (2.0× live) | **2 000** (2.0× live) |
| after mass expiration | 1 000 | 0 | 2 000 |
| after 5 000 churn cycles | 1 000 | **2 699** (2.7× live) | 296 |

tracemalloc: 0.90 MB after build, 0.86 MB current, **1.01 MB peak**.

Interpretation:

* `delete_batch()` and expiration **never remove heap entries** (documented as
  "lazy invalidation"), so `expiry_events` grows with churn: 2 699 entries for
  1 000 live batches after 5 000 insert/delete cycles.
* `lots_by_sku` happens to *shrink* because `fefo_allocation()` pops entries while
  planning and only re-pushes the live/usable ones — cleanup is an accidental
  side effect of allocation, not a deliberate compaction.
* Memory growth is modest at this scale (≈ 1 MB), but the ratio (2.7×) is the
  number to watch if the store grows.

---

## 7. Functions to optimize in the next phase

Ranked by measured impact. "Evidence" = numbers from §4–§6.

### 1. `Inventory.top_k_expiring` — `inventory.py:196` (dominant)

* **Cost:** 1 028 µs/call at 2 000 batches; 973 calls/s; ≈ 2 150–2 190 µs at 4 000 batches.
* **Share of profile:** 73.7 % of cumulative time; `list.sort` alone 65.3 %.
* **Root cause:** builds a list comprehension over **all** of `batches_by_id`, then
  fully sorts it with a Python-level lambda key (`lambda batch: (batch.expiry, batch.batch_id)`),
  called **200 000 times**. The project already maintains a store-wide
  `expiry_events` heap keyed `(sell_by, batch_id, version)` — the exact ordering the
  function needs — and it is never consulted.
* **Symptom of the design gap:** cost is independent of `k` (k=1 ≈ k=100).
* **Optimization direction:** use the existing heap (`heapq.nsmallest` over a copy,
  or pop-and-restore), which makes the cost depend on `k` and the stale-entry count
  rather than on n; avoid the Python lambda by sorting tuples or reading the heap key.

### 2. `list.sort` + `inventory.py:217(<lambda>)` (inside #1)

* **Cost:** 0.105 s self time for 100 queries + 0.020 s in the key function.
* **Direction:** disappears entirely if #1 is re-implemented on the heap; if a sort
  remains, drop the per-element Python callable.

### 3. `Inventory.expire_due` / `HeapManager.pop_due` — `inventory.py:128`, `heap_manager.py:73`

* **Cost:** 0.21 µs per call when **nothing is due** (≈ 4.9 M calls/s), paid on
  *every* dated read — `available()` is 0.37 µs total, so the guard is ~57 % of a
  read. 7 101 calls and 6.3 % of cumulative profile time.
* **Direction:** make the no-op path a single comparison on
  `expiry_events[0][0]` before entering the loop/function, or amortize it
  (only re-check when the caller's date advances).

### 4. `HeapManager.fefo_allocation` — `heap_manager.py:31`

* **Cost:** 7.3 µs for one `reserve` when 100 fully-reserved batches sit at the
  front (vs 3.8 µs baseline, **≈ 1.9×**; repeated sessions measured 6.9–8.3 µs,
  i.e. 1.8–2.2×); 2 878 `heappop` + 4 769 `heappush` calls in
  the mixed run for only 700 reservations.
* **Root cause:** pop-and-re-push for every entry inspected, including entries that
  are skipped (fully reserved / expired). Matches the known weakness in
  `IMPLEMENTATION_NOTES.md` §5.
* **Direction:** stop re-pushing entries that were only *inspected* and not allocated
  (dead, expired and fully-reserved entries are already discarded); each unnecessary
  pop+push pair costs 2 × O(log m).

### 5. `Inventory.insert_batch` + `HeapManager.add_batch` — `inventory.py:88`, `heap_manager.py:16`

* **Cost:** 3.71 µs/insert (2 000 inserts = 7.4 ms); 5.8 % of cumulative profile;
  two `heappush` calls per batch.
* **Direction:** low priority — this is the expected O(log n) write path. Only worth
  touching if bulk loading becomes a requirement.

### 6. Stale-entry accumulation (memory, not CPU)

* `expiry_events` reaches 2 699 entries for 1 000 live batches after churn (2.7×).
* **Direction:** periodic compaction, or tombstones counted separately, if long-lived
  processes are in scope. No CPU impact measured today.

### Not worth optimizing (already at dict/native speed)

`search_batch` 0.47 µs, `delete_batch` 0.38 µs, `cancel_reservation` 0.98 µs,
`fulfill` 1.40 µs, `Batch.available` < 0.1 µs. These are dominated by Python call
overhead, not by algorithm choice.

---

## 8. What this baseline does not cover

* **Thresholds:** no pass/fail budget was set; these are raw numbers only.
* **Line-level attribution:** `line_profiler` is not installed, so hot *lines* inside
  `top_k_expiring` are inferred from `tottime` shares, not measured directly.
* **Concurrency:** the engine is single-threaded by design; no lock contention exists
  to measure.
* **Persistence/IO:** none exists in the project.
* **Scale beyond 4 000 batches** and real supplier data: the dataset is synthetic
  and deliberately uniform (8 SKUs, even spread), so worst cases such as one SKU
  holding all stock are covered only by the targeted case in §4
  ("reserve behind 100 fully-reserved").
* **Python version variance:** all numbers are CPython 3.14.7 only.
