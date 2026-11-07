#!/usr/bin/env python3
"""Baseline performance profiler for the Batch-Aware Inventory Engine.

This script measures the project AS-IS. It imports ``batch``, ``heap_manager``,
``inventory`` and ``reservations`` and never modifies them. All generated data is
deterministic, so runs are comparable before and after optimization.

Usage:
    python3 profiling/profile_baseline.py              # timing + cProfile + memory
    python3 profiling/profile_baseline.py --timing     # wall-clock only
    python3 profiling/profile_baseline.py --profile    # cProfile only
    python3 profiling/profile_baseline.py --memory     # tracemalloc/heap accounting
    python3 profiling/profile_baseline.py --json profiling/baseline.json

Sections are written both to stdout (Markdown tables) and, optionally, to JSON.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import statistics
import sys
import time
import tracemalloc
from datetime import date, timedelta
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from inventory import Inventory              # noqa: E402
from reservations import (                   # noqa: E402
    cancel_reservation,
    fulfill,
    reserve,
)

# ---------------------------------------------------------------- dataset ----

# The "common dataset": a deterministic grocery store snapshot.
BASE_DATE = date(2026, 11, 1)
SKUS = ("milk", "eggs", "bread", "yogurt", "cheese", "juice", "butter", "cream")
N_BATCHES = 2000            # 250 batches per SKU
EXPIRY_BUFFER_DAYS = 3

TIMING_REPEATS = 5
PROFILE_DIR = os.path.dirname(os.path.abspath(__file__))

# A timing case: (setup() -> fresh state, body(state), number of operations).
Case = tuple[Callable[[], Any], Callable[[Any], Any], int]


def build_store(n_batches: int = N_BATCHES, today: date = BASE_DATE) -> Inventory:
    """Build the reference dataset: `n_batches` deliveries across 8 SKUs.

    Batch i: SKU = SKUS[i % 8], quantity 10..49, expiry = today + 4..93 days.
    Deterministic by construction (no RNG), so every run sees identical state.
    """
    inv = Inventory(expiry_buffer_days=EXPIRY_BUFFER_DAYS)
    for i in range(n_batches):
        sku = SKUS[i % len(SKUS)]
        expiry = today + timedelta(days=4 + (i * 7) % 90)
        quantity = 10 + (i * 13) % 40
        inv.insert_batch(f"B{i:05d}", sku, quantity, expiry, today)
    return inv


def batch_ids(n_batches: int = N_BATCHES) -> list[str]:
    return [f"B{i:05d}" for i in range(n_batches)]


def heap_stats(inv: Inventory) -> dict[str, int]:
    """Count live records against heap entries (heap entries include stale ones)."""
    return {
        "live_batches": len(inv.batches_by_id),
        "expiry_heap_entries": len(inv.expiry_events),
        "sku_heap_entries": sum(len(h) for h in inv.lots_by_sku.values()),
        "pending_reports": len(inv._pending_expiry_reports),
        "tracked_available_units": sum(inv.available_by_sku.values()),
    }


# ------------------------------------------------------------ timing cases ---

def _reserve_orders(inv: Inventory, count: int, prefix: str = "ORD",
                    qty: int = 5, today: date = BASE_DATE) -> None:
    for i in range(count):
        reserve(inv, f"{prefix}-{i:04d}", SKUS[i % len(SKUS)], qty, today)


def _case_insert() -> Case:
    def setup() -> date:
        return BASE_DATE

    def body(today: date) -> None:
        build_store(N_BATCHES, today)
    return setup, body, N_BATCHES


def _case_available() -> Case:
    calls = 20000

    def body(inv: Inventory) -> int:
        total = 0
        for i in range(calls):
            total += inv.available(SKUS[i % len(SKUS)], BASE_DATE)
        return total
    return build_store, body, calls


def _case_search() -> Case:
    calls = 20000

    def body(inv: Inventory) -> int:
        hits = 0
        for i in range(calls):
            if i % 2:
                hits += inv.search_batch(f"B{i % N_BATCHES:05d}") is not None
            else:
                hits += inv.search_batch(f"MISS-{i}") is not None
        return hits
    return build_store, body, calls


def _case_reserve() -> Case:
    calls = 500

    def body(inv: Inventory) -> None:
        _reserve_orders(inv, calls)
    return build_store, body, calls


def _case_fulfill() -> Case:
    calls = 500

    def setup() -> Inventory:
        inv = build_store()
        _reserve_orders(inv, calls)
        return inv

    def body(inv: Inventory) -> None:
        for i in range(calls):
            fulfill(inv, f"ORD-{i:04d}", BASE_DATE)
    return setup, body, calls


def _case_cancel() -> Case:
    calls = 500

    def setup() -> Inventory:
        inv = build_store()
        _reserve_orders(inv, calls, prefix="CXL")
        return inv

    def body(inv: Inventory) -> None:
        for i in range(calls):
            cancel_reservation(inv, f"CXL-{i:04d}")
    return setup, body, calls


def _case_expire() -> Case:
    later = BASE_DATE + timedelta(days=200)

    def body(inv: Inventory) -> None:
        inv.process_expired(later)
    return build_store, body, N_BATCHES


def _case_delete() -> Case:
    calls = 500
    ids = batch_ids()[:calls]

    def body(inv: Inventory) -> None:
        for batch_id in ids:
            inv.delete_batch(batch_id)
    return build_store, body, calls


def _case_top_k(k: int, calls: int) -> Case:
    def body(inv: Inventory) -> None:
        for _ in range(calls):
            inv.top_k_expiring(k, BASE_DATE)
    return build_store, body, calls


def _case_expire_due_noop() -> Case:
    """Cost of the expire_due() guard that every `available` call pays."""
    calls = 20000

    def body(inv: Inventory) -> None:
        for _ in range(calls):
            inv.expire_due(BASE_DATE)
    return build_store, body, calls


def _case_reserve_behind_reserved() -> Case:
    """One reserve() that must skip 100 fully-reserved batches first."""
    def setup() -> Inventory:
        inv = build_store()
        milk = sorted(
            (b for b in inv.batches_by_id.values() if b.sku == "milk"),
            key=lambda b: (b.expiry, b.batch_id),
        )[:100]
        for j, batch in enumerate(milk):
            reserve(inv, f"FULL-{j:04d}", "milk", batch.quantity, BASE_DATE)
        return inv

    def body(inv: Inventory) -> None:
        reserve(inv, "TAIL", "milk", 1, BASE_DATE)
    return setup, body, 1


def _case_churn() -> Case:
    cycles = 2000

    def setup() -> Inventory:
        return build_store(300)

    def body(inv: Inventory) -> None:
        today = BASE_DATE
        for i in range(cycles):
            batch_id = f"C{i:05d}"
            sku = SKUS[i % len(SKUS)]
            inv.insert_batch(batch_id, sku, 12, today + timedelta(days=30), today)
            reserve(inv, batch_id, sku, 1, today)
            fulfill(inv, batch_id, today)
            inv.delete_batch(batch_id)
            if i % 100 == 0:
                today += timedelta(days=1)
                inv.process_expired(today)
    return setup, body, cycles


def timing_cases() -> list[tuple[str, Callable[[], Any], Callable[[Any], Any], int]]:
    cases = [
        ("insert_batch", *_case_insert()),
        ("available", *_case_available()),
        ("search_batch", *_case_search()),
        ("reserve", *_case_reserve()),
        ("fulfill", *_case_fulfill()),
        ("cancel_reservation", *_case_cancel()),
        ("process_expired (all due)", *_case_expire()),
        ("delete_batch", *_case_delete()),
        ("expire_due (nothing due)", *_case_expire_due_noop()),
        ("reserve behind 100 fully-reserved", *_case_reserve_behind_reserved()),
        ("top_k_expiring(10)", *_case_top_k(10, 200)),
        ("top_k_expiring(2000)", *_case_top_k(2000, 50)),
        ("churn (insert+reserve+fulfill+delete+expire)", *_case_churn()),
    ]
    return cases


def run_timing(repeats: int = TIMING_REPEATS) -> list[dict]:
    """Time each workload `repeats` times and keep the median.

    Each repeat gets a freshly built store (setup excluded from the measurement)
    so state never leaks between repeats.
    """
    rows = []
    for name, setup, body, ops in timing_cases():
        samples = []
        for _ in range(repeats):
            state = setup()
            start = time.perf_counter()
            body(state)
            samples.append(time.perf_counter() - start)
        median = statistics.median(samples)
        rows.append({
            "case": name,
            "ops": ops,
            "repeats": repeats,
            "median_s": median,
            "min_s": min(samples),
            "max_s": max(samples),
            "us_per_op": median / ops * 1e6,
            "ops_per_sec": ops / median if median else float("inf"),
        })
    return rows


def print_timing_table(rows: list[dict]) -> None:
    print("\n## Wall-clock baseline (median of {} runs)\n".format(TIMING_REPEATS))
    print("| workload | ops | median | per-op | ops/sec |")
    print("|---|---:|---:|---:|---:|")
    for r in rows:
        print("| `{}` | {} | {:.3f} ms | {:.2f} us | {:,.0f} |".format(
            r["case"], r["ops"], r["median_s"] * 1e3, r["us_per_op"],
            r["ops_per_sec"]))


# ------------------------------------------------------------- top-k scaling --

def run_top_k_scaling() -> list[dict]:
    """Show how top_k_expiring scales with store size and with k."""
    rows = []
    sizes = (250, 500, 1000, 2000, 4000)
    for size in sizes:
        inv = build_store(size)
        for k in (1, 10, 100):
            calls = 20
            samples = []
            for _ in range(calls):
                start = time.perf_counter()
                inv.top_k_expiring(k, BASE_DATE)
                samples.append(time.perf_counter() - start)
            rows.append({
                "store_size": size,
                "k": k,
                "us_per_call": statistics.median(samples) * 1e6,
            })
    return rows


def print_top_k_scaling(rows: list[dict]) -> None:
    print("\n### `top_k_expiring` scaling (median per call)\n")
    by_k: dict[int, dict[int, float]] = {}
    for r in rows:
        by_k.setdefault(r["k"], {})[r["store_size"]] = r["us_per_call"]
    sizes = sorted({r["store_size"] for r in rows})
    print("| store size | " + " | ".join(f"k={k}" for k in sorted(by_k)) + " |")
    print("|---:|" + "---:|" * len(by_k))
    for size in sizes:
        cells = " | ".join(f"{by_k[k][size]:.1f} us" for k in sorted(by_k))
        print(f"| {size} | {cells} |")


# ------------------------------------------------------------ cProfile pass --

def profile_workload() -> None:
    """Mixed read/write workload used for the cProfile snapshot."""
    inv = build_store(N_BATCHES)

    for i in range(6000):                       # warm reads
        inv.available(SKUS[i % len(SKUS)], BASE_DATE)
    for i in range(6000):                       # point lookups
        inv.search_batch(f"B{i % N_BATCHES:05d}")
    for _ in range(100):                        # store-wide query
        inv.top_k_expiring(10, BASE_DATE)

    for i in range(400):                        # reserve + fulfill
        reserve(inv, f"ORD-{i:04d}", SKUS[i % len(SKUS)], 5, BASE_DATE)
    for i in range(400):
        fulfill(inv, f"ORD-{i:04d}", BASE_DATE)

    for i in range(300):                        # reserve + cancel
        reserve(inv, f"CXL-{i:04d}", SKUS[i % len(SKUS)], 5, BASE_DATE)
    for i in range(300):
        cancel_reservation(inv, f"CXL-{i:04d}")

    inv.process_expired(BASE_DATE + timedelta(days=95))   # mass expiration
    for batch_id in batch_ids()[:300]:                    # deletions
        inv.delete_batch(batch_id)


def run_profile(top: int = 30) -> dict:
    """Profile `profile_workload` with the C profiler (cProfile)."""
    profiler = cProfile.Profile()
    profiler.enable()
    profile_workload()
    profiler.disable()

    prof_path = os.path.join(PROFILE_DIR, "baseline.prof")
    profiler.dump_stats(prof_path)

    def top_lines(sort_key: str, count: int) -> str:
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats(sort_key).print_stats(count)
        return stream.getvalue()

    by_tottime = top_lines("tottime", top)
    by_cumtime = top_lines("cumulative", top)

    text_path = os.path.join(PROFILE_DIR, "baseline_profile.txt")
    with open(text_path, "w", encoding="utf-8") as handle:
        handle.write("=== sorted by tottime ===\n")
        handle.write(by_tottime)
        handle.write("\n=== sorted by cumulative ===\n")
        handle.write(by_cumtime)

    print("\n## cProfile: sorted by tottime (self time)\n")
    print(by_tottime)
    print("## cProfile: sorted by cumulative time\n")
    print(by_cumtime)

    stats = pstats.Stats(profiler)
    entries = getattr(stats, "stats")
    return {
        "prof_file": prof_path,
        "text_dump": text_path,
        "total_calls": getattr(stats, "total_calls"),
        "total_time_s": getattr(stats, "total_tt"),
        "functions": [
            {
                "function": f"{func} ({os.path.basename(filename)}:{line})",
                "tottime_s": data[2],
                "cumtime_s": data[3],
                "ncalls": data[1],
            }
            for (filename, line, func), data in sorted(
                entries.items(), key=lambda item: item[1][3], reverse=True
            )
        ],
    }


# ---------------------------------------------------------------- memory ----

def run_memory() -> dict:
    """Heap accounting + tracemalloc for a churn scenario."""
    tracemalloc.start()
    inv = build_store(N_BATCHES)
    after_build = heap_stats(inv)
    after_build_mem = tracemalloc.get_traced_memory()

    for batch_id in batch_ids()[:1000]:          # delete half -> stale entries
        inv.delete_batch(batch_id)
    after_delete = heap_stats(inv)

    inv.process_expired(BASE_DATE + timedelta(days=200))
    after_expire = heap_stats(inv)

    today = BASE_DATE
    for i in range(5000):                        # churn
        batch_id = f"C{i:05d}"
        sku = SKUS[i % len(SKUS)]
        inv.insert_batch(batch_id, sku, 12, today + timedelta(days=30), today)
        reserve(inv, batch_id, sku, 1, today)
        fulfill(inv, batch_id, today)
        inv.delete_batch(batch_id)
        if i % 100 == 0:
            today += timedelta(days=1)
            inv.process_expired(today)
    after_churn = heap_stats(inv)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result = {
        "after_build": after_build,
        "after_delete_1000": after_delete,
        "after_expire_all": after_expire,
        "after_churn_5000": after_churn,
        "traced_current_mb": current / 1024 / 1024,
        "traced_peak_mb": peak / 1024 / 1024,
        "traced_after_build_mb": after_build_mem[0] / 1024 / 1024,
    }

    print("\n## Heap accounting (live records vs heap entries)\n")
    print("| phase | live batches | expiry heap entries | sku heap entries |")
    print("|---|---:|---:|---:|")
    for phase, key in (
        ("after build (2000)", "after_build"),
        ("after deleting 1000", "after_delete_1000"),
        ("after mass expiration", "after_expire_all"),
        ("after 5000 churn cycles", "after_churn_5000"),
    ):
        stats = result[key]
        print("| {} | {} | {} | {} |".format(
            phase, stats["live_batches"], stats["expiry_heap_entries"],
            stats["sku_heap_entries"]))
    print("\ntracemalloc: after build {:.2f} MB, current {:.2f} MB, peak {:.2f} MB".format(
        result["traced_after_build_mb"], result["traced_current_mb"],
        result["traced_peak_mb"]))
    return result


# ------------------------------------------------------------------ main ----

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing", action="store_true", help="wall-clock cases only")
    parser.add_argument("--profile", action="store_true", help="cProfile pass only")
    parser.add_argument("--memory", action="store_true", help="heap/memory pass only")
    parser.add_argument("--scaling", action="store_true", help="top_k scaling only")
    parser.add_argument("--json", default=None, help="write results as JSON here")
    parser.add_argument("--top", type=int, default=30, help="profile rows to print")
    args = parser.parse_args(argv)

    explicit = args.timing or args.profile or args.memory or args.scaling
    do_timing = args.timing or not explicit
    do_profile = args.profile or not explicit
    do_memory = args.memory or not explicit
    do_scaling = args.scaling or not explicit

    print("Batch-Aware Inventory Engine - baseline profile")
    print("python {} | dataset: {} batches, {} SKUs, base date {}".format(
        sys.version.split()[0], N_BATCHES, len(SKUS), BASE_DATE))

    results: dict = {
        "python": sys.version,
        "platform": sys.platform,
        "dataset": {
            "batches": N_BATCHES,
            "skus": list(SKUS),
            "base_date": BASE_DATE.isoformat(),
            "expiry_buffer_days": EXPIRY_BUFFER_DAYS,
        },
    }

    if do_timing:
        results["timing"] = run_timing()
        print_timing_table(results["timing"])
    if do_scaling:
        results["top_k_scaling"] = run_top_k_scaling()
        print_top_k_scaling(results["top_k_scaling"])
    if do_profile:
        results["profile"] = run_profile(args.top)
    if do_memory:
        results["memory"] = run_memory()

    if args.json:
        path = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
        print(f"\nWrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
