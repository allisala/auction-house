"""Auction rules: one highest bid, optimistic concurrency, idempotent retries."""

import copy
import threading
import uuid
from datetime import datetime, timezone

LOTS = {
    "001": {
        "title": "Victorian Pocket Watch",
        "note": "No. 14, still ticking",
        "start": 120,
        "increment": 10,
    },
    "002": {
        "title": "Room With No Door",
        "note": "Oil painting, unsigned",
        "start": 500,
        "increment": 25,
    },
    "003": {
        "title": "The Travelling Remington",
        "note": "Portable typewriter, 1934",
        "start": 80,
        "increment": 5,
    },
}


def utc_now():
    """Return the current UTC time as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_time(text):
    """Read a UTC timestamp written by utc_now."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def new_bid_id():
    """Make an id that stays unique when many bids arrive together."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return stamp + "-" + uuid.uuid4().hex[:8]


def fresh_lot(lot_id, deadline):
    """Open one lot at its starting price. Version 0 is the first etag."""
    spec = LOTS[lot_id]
    return {
        "lot_id": lot_id,
        "title": spec["title"],
        "note": spec["note"],
        "start": spec["start"],
        "increment": spec["increment"],
        "highest": spec["start"],
        "leader": None,
        "leader_bid": None,
        "deadline": deadline,
        "applied": {},
        "version": 0,
    }


def check_bid(body, now_text):
    """Check the incoming bid and fill in the server timestamp."""
    if not isinstance(body, dict):
        raise ValueError("Send a JSON object.")
    lot_id = str(body.get("lot_id", "")).strip()
    if lot_id not in LOTS:
        raise ValueError("Lot must be 001, 002, or 003.")
    bidder = str(body.get("bidder", "")).strip()
    if bidder == "" or len(bidder) > 40:
        raise ValueError("Send a bidder name, up to 40 characters.")
    try:
        amount = int(body["amount"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Amount must be a whole number of pounds.")
    if amount < 0 or amount > 10000000:
        raise ValueError("Amount is out of range.")
    return {
        "bid_id": new_bid_id(),
        "lot_id": lot_id,
        "bidder": bidder,
        "amount": amount,
        "submitted_at": now_text,
        "seen_price": int(body.get("seen_price", LOTS[lot_id]["start"])),
    }


def judge(state, bid):
    """Decide one bid against the price stored right now."""
    if bid["bid_id"] in state["applied"]:
        return dict(state["applied"][bid["bid_id"]])
    if parse_time(bid["submitted_at"]) > parse_time(state["deadline"]):
        return _outcome(bid, False, "late", state)
    need = state["highest"] + state["increment"]
    if bid["amount"] < need:
        reason = "outbid" if bid["amount"] >= bid["seen_price"] + state["increment"] else "too_low"
        return _outcome(bid, False, reason, state)
    return _outcome(bid, True, "accepted", state)


def _outcome(bid, accepted, reason, state):
    """Build the result row for one bid."""
    return {
        "bid_id": bid["bid_id"],
        "lot_id": bid["lot_id"],
        "bidder": bid["bidder"],
        "amount": bid["amount"],
        "accepted": accepted,
        "reason": reason,
        "highest_at_decision": state["highest"],
        "leader_at_decision": state["leader"],
    }


def apply_decision(state, bid, outcome):
    """Remember the decision. An accept also moves the highest bid."""
    nxt = copy.deepcopy(state)
    nxt["applied"][bid["bid_id"]] = outcome
    if outcome["accepted"]:
        nxt["highest"] = bid["amount"]
        nxt["leader"] = bid["bidder"]
        nxt["leader_bid"] = bid["bid_id"]
        outcome["highest_at_decision"] = state["highest"]
        nxt["applied"][bid["bid_id"]] = dict(outcome)
    nxt["version"] = state["version"] + 1
    return nxt


class MemoryHouse:
    """In-memory lots with compare-and-swap on the version number."""

    def __init__(self, deadline, lot_ids):
        self._lock = threading.Lock()
        self.conflicts = 0
        self.docs = {lot_id: fresh_lot(lot_id, deadline) for lot_id in lot_ids}

    def read(self, lot_id):
        """Return a copy of the lot and its current version."""
        with self._lock:
            state = self.docs[lot_id]
            return copy.deepcopy(state), state["version"]

    def cas(self, lot_id, version, new_state):
        """Store new_state only when version is still current."""
        with self._lock:
            current = self.docs[lot_id]
            if current["version"] != version:
                self.conflicts += 1
                return False
            self.docs[lot_id] = new_state
            return True


def process_bid_counted(house, bid, retries=80):
    """Apply one bid and count how many compare-and-swap attempts failed."""
    attempts = 0
    for _ in range(retries):
        state, version = house.read(bid["lot_id"])
        if bid["bid_id"] in state["applied"]:
            return dict(state["applied"][bid["bid_id"]]), attempts
        outcome = judge(state, bid)
        new_state = apply_decision(state, bid, outcome)
        if house.cas(bid["lot_id"], version, new_state):
            return outcome, attempts
        attempts += 1
    return {
        "bid_id": bid["bid_id"],
        "lot_id": bid["lot_id"],
        "bidder": bid["bidder"],
        "amount": bid["amount"],
        "accepted": False,
        "reason": "gave_up",
        "highest_at_decision": None,
        "leader_at_decision": None,
    }, attempts
