"""Check the auction rules: one price, no double apply, no stale overwrite."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import auction

DEADLINE = "2026-11-03 18:00:00"
PASSED = 0
FAILED = 0


def check(name, ok):
    """Print one check and count it."""
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("pass", name)
    else:
        FAILED += 1
        print("FAIL", name)


def bid(bid_id, amount, when="2026-11-03 17:50:00", bidder="Ada"):
    """One bid against lot 001, which opens at £120."""
    return {
        "bid_id": bid_id,
        "lot_id": "001",
        "bidder": bidder,
        "amount": amount,
        "submitted_at": when,
        "seen_price": 120,
    }


def test_price_only_rises():
    """A lower bid cannot replace a higher one."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    auction.process_bid_counted(house, bid("a", 200, bidder="Ann"))
    auction.process_bid_counted(house, bid("b", 150, bidder="Ben"))
    state, _ = house.read("001")
    check("price does not fall", state["highest"] == 200 and state["leader"] == "Ann")


def test_duplicate_does_not_apply_twice():
    """The same bid id is judged once."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    offer = bid("same", 180, bidder="Bob")
    auction.process_bid_counted(house, offer)
    auction.process_bid_counted(house, offer)
    state, _ = house.read("001")
    check("duplicate bid stays at one write", state["highest"] == 180 and state["version"] == 1)


def test_stale_write_loses():
    """A write that carries an old version does not land."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    state, version = house.read("001")
    auction.process_bid_counted(house, bid("fresh", 200, bidder="Cara"))
    stale = auction.apply_decision(state, bid("stale", 300, bidder="Dan"), {
        "bid_id": "stale",
        "lot_id": "001",
        "bidder": "Dan",
        "amount": 300,
        "accepted": True,
        "reason": "accepted",
        "highest_at_decision": 120,
        "leader_at_decision": None,
    })
    landed = house.cas("001", version, stale)
    current, _ = house.read("001")
    check("stale version is rejected", (not landed) and current["leader"] == "Cara" and current["highest"] == 200)


def test_late_bid_is_rejected():
    """A bid after the deadline does not become the leader."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    auction.process_bid_counted(house, bid("late", 500, when="2026-11-03 18:00:01", bidder="Sam"))
    state, _ = house.read("001")
    check("late bid is not the leader", state["leader"] is None and state["applied"]["late"]["reason"] == "late")


def test_one_leader_under_threads():
    """Many bids leave one leader, and the price is the highest bid that was accepted."""
    house = auction.MemoryHouse(DEADLINE, ["001"])
    offers = [bid(f"t{i}", 120 + 10 * ((i % 20) + 1), bidder=f"b{i}") for i in range(40)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda item: auction.process_bid_counted(house, item), offers))
    state, _ = house.read("001")
    accepted = [item for item in state["applied"].values() if item["accepted"]]
    check(
        "one leader after concurrent bids",
        state["leader"] is not None
        and state["highest"] == max(item["amount"] for item in accepted)
        and state["version"] == len(state["applied"]),
    )


def main():
    test_price_only_rises()
    test_duplicate_does_not_apply_twice()
    test_stale_write_loses()
    test_late_bid_is_rejected()
    test_one_leader_under_threads()
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
