"""Repeat the local contention model and summarise the spread across runs."""

import csv
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import auction

FIGURES = os.path.join(ROOT, "figures")
RESULTS = os.path.join(ROOT, "results")
DEADLINE = "2026-11-03 18:00:00"
BIDS = 1000
REPEATS = 5
LOT_COUNTS = [1, 5, 10, 20]
INK = "#1c1915"
PAPER = "#f6f1e7"
CREAM = "#fffaf2"
BLUE = "#2c4c7c"
RED = "#8d3b32"


def blank_lot(lot_id):
    """Open a lot at the pocket-watch prices."""
    state = auction.fresh_lot("001", DEADLINE)
    state["lot_id"] = lot_id
    state["title"] = "Lot " + lot_id
    return state


def make_bids(lot_ids, seed):
    """Build 1000 bids that all saw £120."""
    rng = random.Random(seed)
    bids = []
    for i in range(BIDS):
        steps = rng.randint(1, 40)
        bids.append({
            "bid_id": f"r{seed}-{i:04d}",
            "lot_id": lot_ids[i % len(lot_ids)],
            "bidder": f"bidder-{i:04d}",
            "amount": 120 + steps * 10,
            "submitted_at": "2026-11-03 17:59:00",
            "seen_price": 120,
        })
    rng.shuffle(bids)
    return bids


def one_run(n_lots, seed):
    """Process 1000 bids and return the time, clashes, and abandoned bids."""
    lot_ids = [f"{i:03d}" for i in range(1, n_lots + 1)]
    house = auction.MemoryHouse(DEADLINE, [])
    house.docs = {lot_id: blank_lot(lot_id) for lot_id in lot_ids}
    house.conflicts = 0
    bids = make_bids(lot_ids, seed)
    started = time.perf_counter()
    workers = min(32, len(bids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda item: auction.process_bid_counted(house, item), bids))
    elapsed = time.perf_counter() - started
    gave_up = sum(1 for outcome, _ in rows if outcome["reason"] == "gave_up")
    return {
        "lots": n_lots,
        "seed": seed,
        "seconds": round(elapsed, 4),
        "clashes": house.conflicts,
        "abandoned": gave_up,
    }


def median(values):
    """Median of a short list."""
    return statistics.median(values)


def main():
    os.makedirs(FIGURES, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    rows = []
    for n_lots in LOT_COUNTS:
        for repeat in range(REPEATS):
            row = one_run(n_lots, 7 + repeat)
            rows.append(row)
            print(row, flush=True)
    path = os.path.join(RESULTS, "repeated_contention.csv")
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for n_lots in LOT_COUNTS:
        group = [row for row in rows if row["lots"] == n_lots]
        summary.append({
            "lots": n_lots,
            "median_s": round(median([row["seconds"] for row in group]), 4),
            "min_s": min(row["seconds"] for row in group),
            "max_s": max(row["seconds"] for row in group),
            "median_clashes": int(median([row["clashes"] for row in group])),
            "min_clashes": min(row["clashes"] for row in group),
            "max_clashes": max(row["clashes"] for row in group),
            "median_abandoned": int(median([row["abandoned"] for row in group])),
            "max_abandoned": max(row["abandoned"] for row in group),
        })
        print("SUMMARY", summary[-1], flush=True)

    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(CREAM)
    xs = [row["lots"] for row in summary]
    ys = [row["median_clashes"] for row in summary]
    lows = [row["median_clashes"] - row["min_clashes"] for row in summary]
    highs = [row["max_clashes"] - row["median_clashes"] for row in summary]
    ax.errorbar(xs, ys, yerr=[lows, highs], fmt="-o", color=RED, lw=2, capsize=4)
    ax.set_xticks(xs)
    ax.set_xlabel("Lots sharing 1,000 bids")
    ax.set_ylabel("Compare-and-swap clashes")
    ax.set_title("Five local runs at each lot count")
    ax.tick_params(colors=INK, labelsize=10)
    for spine in ax.spines.values():
        spine.set_color("#d9d0c2")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "repeated_contention.png"), bbox_inches="tight", facecolor=PAPER)
    print("Wrote", path)


if __name__ == "__main__":
    main()
