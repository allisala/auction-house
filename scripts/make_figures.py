"""Run the auction rules on my laptop and draw the pictures."""

import csv
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import auction

FIGURES = os.path.join(ROOT, "figures")
RESULTS = os.path.join(ROOT, "results")
DEADLINE = "2026-11-03 18:00:00"
INK = "#1c1915"
PAPER = "#f6f1e7"
GOLD = "#a56b2b"
GREEN = "#1f6f54"
RED = "#8d3b32"
BLUE = "#2c4c7c"
CREAM = "#fffaf2"


def blank_lot(lot_id, title):
    """Open a lot with the pocket-watch prices, under its own id."""
    state = auction.fresh_lot("001", DEADLINE)
    state["lot_id"] = lot_id
    state["title"] = title
    return state


def make_bids(count, lot_ids, seed):
    """Build bids that all saw the starting price of £120."""
    rng = random.Random(seed)
    bids = []
    for i in range(count):
        lot_id = lot_ids[i % len(lot_ids)]
        steps = rng.randint(1, 40)
        bids.append({
            "bid_id": f"b{seed}-{i:04d}",
            "lot_id": lot_id,
            "bidder": f"bidder-{i:04d}",
            "amount": 120 + steps * 10,
            "submitted_at": "2026-11-03 17:59:00",
            "seen_price": 120,
        })
    rng.shuffle(bids)
    return bids


def run_case(bids, lot_ids, titles):
    """Process every bid at once and count clashes."""
    house = auction.MemoryHouse(DEADLINE, [])
    house.docs = {lot_id: blank_lot(lot_id, titles[lot_id]) for lot_id in lot_ids}
    house.conflicts = 0
    started = time.perf_counter()
    workers = min(32, max(1, len(bids)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda bid: auction.process_bid_counted(house, bid), bids))
    elapsed = time.perf_counter() - started
    outcomes = [row[0] for row in rows]
    attempts = sum(row[1] for row in rows)
    watched = house.read(lot_ids[0])[0]
    summary = {
        "bids": len(bids),
        "lots": len(lot_ids),
        "seconds": round(elapsed, 4),
        "accepted": sum(1 for item in outcomes if item["reason"] == "accepted"),
        "too_low": sum(1 for item in outcomes if item["reason"] == "too_low"),
        "outbid": sum(1 for item in outcomes if item["reason"] == "outbid"),
        "late": sum(1 for item in outcomes if item["reason"] == "late"),
        "gave_up": sum(1 for item in outcomes if item["reason"] == "gave_up"),
        "clashes": house.conflicts,
        "retries": attempts,
        "highest": watched["highest"],
        "leader": watched["leader"] or "",
        "top_offer": max(bid["amount"] for bid in bids),
    }
    finals = []
    for lot_id in lot_ids:
        state, _ = house.read(lot_id)
        finals.append(state)
    return summary, finals, outcomes


def pocket_watch_story():
    """Play Alice, Bob, and Charlie in a fixed order, then once more out of order."""
    people = [
        ("Alice", 150),
        ("Bob", 180),
        ("Charlie", 160),
    ]
    ordered = _play(people, ["Alice", "Bob", "Charlie"])
    shuffled = _play(people, ["Charlie", "Alice", "Bob"])
    return ordered, shuffled


def _play(people, order):
    """Apply three named bids in one order."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    by_name = {}
    for name, amount in people:
        by_name[name] = {
            "bid_id": "story-" + name.lower(),
            "lot_id": "001",
            "bidder": name,
            "amount": amount,
            "submitted_at": "2026-11-03 17:50:00",
            "seen_price": 120,
        }
    rows = []
    for name in order:
        outcome, clashes = auction.process_bid_counted(house, by_name[name])
        state, _ = house.read("001")
        rows.append({
            "bidder": name,
            "amount": by_name[name]["amount"],
            "reason": outcome["reason"],
            "highest_after": state["highest"],
            "leader": state["leader"],
            "clashes": clashes,
        })
    return rows


def last_second():
    """A few bids in the final minute, including some that miss the deadline."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    script = [
        ("Mina", 200, "2026-11-03 17:59:31"),
        ("Owen", 260, "2026-11-03 17:59:44"),
        ("Priya", 310, "2026-11-03 17:59:58"),
        ("Sam", 400, "2026-11-03 18:00:01"),
        ("Noor", 450, "2026-11-03 18:00:06"),
    ]
    rows = []
    for name, amount, when in script:
        bid = {
            "bid_id": "late-" + name.lower(),
            "lot_id": "001",
            "bidder": name,
            "amount": amount,
            "submitted_at": when,
            "seen_price": 120,
        }
        outcome, _ = auction.process_bid_counted(house, bid)
        state, _ = house.read("001")
        rows.append({
            "bidder": name,
            "amount": amount,
            "at": when,
            "reason": outcome["reason"],
            "highest": state["highest"],
            "leader": state["leader"],
        })
    return rows


def save_csv(path, rows):
    """Write a table."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def style_ax(ax):
    """Plain axes on the paper background."""
    ax.set_facecolor(CREAM)
    ax.tick_params(colors=INK, labelsize=10)
    for spine in ax.spines.values():
        spine.set_color("#d9d0c2")
    ax.title.set_color(INK)


def draw_workflow():
    """Draw the three functions and the two queues."""
    fig, ax = plt.subplots(figsize=(11.2, 6.4), dpi=140)
    fig.patch.set_facecolor(PAPER)
    ax.set_xlim(0, 112)
    ax.set_ylim(0, 64)
    ax.axis("off")
    ax.set_facecolor(PAPER)
    ax.text(6, 59, "The Auction House", fontsize=16, color=INK, fontweight="bold")
    ax.text(6, 55, "One bid comes in. A queue carries it. The price moves once.", fontsize=11, color="#5c564c")

    def box(x, y, w, h, face, title, lines):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                facecolor=face, edgecolor=INK, linewidth=1.1)
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h - 4.2, title, ha="center", va="center", fontsize=11, color=INK, fontweight="bold")
        for i, line in enumerate(lines):
            ax.text(x + w / 2, y + h - 9 - i * 4, line, ha="center", va="center", fontsize=9, color="#3d3832")

    box(4, 28, 22, 20, "#f3e0c4", "Bidder", ["POST /api/bids", "lot, name, amount"])
    box(32, 28, 24, 20, "#d9e4f2", "receive_bid", ["HTTP trigger", "store the request"])
    box(62, 28, 24, 20, "#e7f0ea", "process_bid", ["queue trigger", "compare-and-swap"])
    box(32, 4, 24, 16, "#efe7f6", "incoming-bids", ["id and file name"])
    box(62, 4, 24, 16, "#efe7f6", "bid-results", ["id and decision"])
    box(90, 16, 18, 20, "#f8e4df", "record_result", ["queue trigger", "one result file"])

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.2))

    arrow(26, 38, 32, 38)
    arrow(44, 28, 44, 20)
    arrow(56, 12, 62, 28)
    arrow(74, 28, 74, 20)
    arrow(86, 12, 90, 24)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "workflow.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_lots():
    """Draw the three catalogue cards."""
    fig, ax = plt.subplots(figsize=(11.2, 4.6), dpi=140)
    fig.patch.set_facecolor(PAPER)
    ax.set_xlim(0, 112)
    ax.set_ylim(0, 46)
    ax.axis("off")
    cards = [
        ("001", "Victorian Pocket Watch", "No. 14, still ticking", "£120", "£10"),
        ("002", "Room With No Door", "Oil painting, unsigned", "£500", "£25"),
        ("003", "The Travelling Remington", "Portable typewriter, 1934", "£80", "£5"),
    ]
    colors = ["#f3e0c4", "#d9e4f2", "#e7f0ea"]
    for i, (number, title, note, start, step) in enumerate(cards):
        x = 4 + i * 36
        patch = FancyBboxPatch((x, 4), 33, 38, boxstyle="round,pad=0.4,rounding_size=1.2",
                                facecolor=colors[i], edgecolor=INK, linewidth=1.1)
        ax.add_patch(patch)
        ax.text(x + 2.2, 36, "LOT " + number, fontsize=10, color=GOLD, fontweight="bold")
        ax.text(x + 2.2, 30, title, fontsize=12, color=INK, fontweight="bold")
        ax.text(x + 2.2, 25, note, fontsize=10, color="#5c564c")
        ax.text(x + 2.2, 16, start, fontsize=18, color=INK, fontweight="bold")
        ax.text(x + 2.2, 11, "starting price", fontsize=9, color="#5c564c")
        ax.text(x + 2.2, 7, "minimum rise " + step, fontsize=9, color="#5c564c")
    fig.savefig(os.path.join(FIGURES, "lots.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_war(rows):
    """Show the pocket-watch price after each of the three bids."""
    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    style_ax(ax)
    labels = ["Open"] + [row["bidder"] + "\n£" + str(row["amount"]) for row in rows]
    prices = [120] + [row["highest_after"] for row in rows]
    colors = [GOLD] + [GREEN if row["reason"] == "accepted" else RED for row in rows]
    ax.plot(range(len(prices)), prices, color=INK, lw=1.4, zorder=1)
    ax.scatter(range(len(prices)), prices, s=80, c=colors, zorder=2)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Highest bid (£)")
    ax.set_title("Pocket watch, Alice then Bob then Charlie")
    for i, row in enumerate(rows):
        word = "accepted" if row["reason"] == "accepted" else "rejected"
        ax.text(i + 1, row["highest_after"] + 4, word, ha="center", fontsize=9, color=colors[i + 1])
    ax.set_ylim(100, 210)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "pocket_watch.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_contention(one, many):
    """Compare failed compare-and-swap attempts."""
    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    style_ax(ax)
    xs = range(len(one))
    labels = [str(row["bids"]) for row in one]
    w = 0.36
    ax.bar([i - w / 2 for i in xs], [row["clashes"] for row in one], width=w, color=RED, label="One lot")
    ax.bar([i + w / 2 for i in xs], [row["clashes"] for row in many], width=w, color=GREEN, label="Twenty lots")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels)
    ax.set_xlabel("Bids submitted together")
    ax.set_ylabel("Failed compare-and-swap attempts")
    ax.set_title("Contention when everyone wants the same lot")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "contention.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_outcomes(one):
    """Stack accepted, outbid, and too-low bids for the single lot."""
    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    style_ax(ax)
    labels = [str(row["bids"]) for row in one]
    accepted = [row["accepted"] for row in one]
    outbid = [row["outbid"] for row in one]
    gave = [row["gave_up"] for row in one]
    ax.bar(labels, accepted, color=GREEN, label="Accepted")
    ax.bar(labels, outbid, bottom=accepted, color=GOLD, label="Outbid while waiting")
    bottom = [a + b for a, b in zip(accepted, outbid)]
    ax.bar(labels, gave, bottom=bottom, color=RED, label="Gave up after 80 clashes")
    ax.set_xlabel("Bids on the pocket watch")
    ax.set_ylabel("Bids")
    ax.set_title("What happened to each bid")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "outcomes.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_latency(one, many):
    """Compare how long each batch took."""
    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    style_ax(ax)
    xs = [row["bids"] for row in one]
    ax.plot(xs, [row["seconds"] for row in one], marker="o", color=RED, label="One lot")
    ax.plot(xs, [row["seconds"] for row in many], marker="o", color=GREEN, label="Twenty lots")
    ax.set_xlabel("Bids submitted together")
    ax.set_ylabel("Seconds on my laptop")
    ax.set_title("Time until every bid has a decision")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "latency.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def draw_last_second(rows):
    """Mark which of the final bids arrived after 18:00."""
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=140)
    fig.patch.set_facecolor(PAPER)
    style_ax(ax)
    names = [row["bidder"] for row in rows]
    amounts = [row["amount"] for row in rows]
    colors = [GREEN if row["reason"] == "accepted" else RED for row in rows]
    ax.bar(names, amounts, color=colors)
    ax.axhline(120, color=GOLD, lw=1, linestyle="--")
    ax.set_ylabel("Bid (£)")
    ax.set_title("Last minute of the pocket watch")
    for i, row in enumerate(rows):
        ax.text(i, row["amount"] + 8, row["reason"].replace("_", " "), ha="center", fontsize=9, color=colors[i])
    ax.set_ylim(0, 520)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "last_second.png"), bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def main():
    os.makedirs(FIGURES, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    sizes = [10, 50, 100, 500, 1000]
    one_rows = []
    many_rows = []
    one_titles = {"001": "Victorian Pocket Watch"}
    many_ids = [f"{i:03d}" for i in range(1, 21)]
    many_titles = {lot_id: "Victorian Pocket Watch" if lot_id == "001" else "Side room " + lot_id for lot_id in many_ids}
    for count in sizes:
        one_bids = make_bids(count, ["001"], 7)
        summary, _, _ = run_case(one_bids, ["001"], one_titles)
        summary["spread"] = "one"
        one_rows.append(summary)
        many_bids = make_bids(count, many_ids, 7)
        summary, _, _ = run_case(many_bids, many_ids, many_titles)
        summary["spread"] = "twenty"
        many_rows.append(summary)
        print("one", one_rows[-1])
        print("twenty", many_rows[-1])

    save_csv(os.path.join(RESULTS, "one_lot.csv"), one_rows)
    save_csv(os.path.join(RESULTS, "twenty_lots.csv"), many_rows)
    ordered, shuffled = pocket_watch_story()
    late = last_second()
    save_csv(os.path.join(RESULTS, "pocket_watch_order.csv"), ordered)
    save_csv(os.path.join(RESULTS, "pocket_watch_other_order.csv"), shuffled)
    save_csv(os.path.join(RESULTS, "last_second.csv"), late)
    print("ORDER", ordered)
    print("OTHER", shuffled)
    print("LATE", late)

    # A repeated delivery must not raise the price twice.
    house = auction.MemoryHouse(DEADLINE, ["001"])
    bid = {
        "bid_id": "twice",
        "lot_id": "001",
        "bidder": "Bob",
        "amount": 180,
        "submitted_at": "2026-11-03 17:50:00",
        "seen_price": 120,
    }
    auction.process_bid_counted(house, bid)
    auction.process_bid_counted(house, bid)
    state, _ = house.read("001")
    print("DUP", state["highest"], state["leader"])

    draw_workflow()
    draw_lots()
    draw_war(ordered)
    draw_contention(one_rows, many_rows)
    draw_outcomes(one_rows)
    draw_latency(one_rows, many_rows)
    draw_last_second(late)
    print("Wrote figures")


if __name__ == "__main__":
    main()
