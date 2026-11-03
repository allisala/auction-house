"""Send separated Azure batches and write the log query that times them."""

import csv
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://auction-house-b2fjhsc3gneda8cw.switzerlandnorth-01.azurewebsites.net/api/bids"
OUT = os.path.join(ROOT, "results", "new-tests", "e2e_batches.csv")
QUERY = os.path.join(ROOT, "results", "new-tests", "e2e_query.kusto")
# Seconds to wait after each batch so the queue can finish before the next one starts.
PAUSES = {1: 60, 5: 90, 10: 120, 20: 180, 50: 240, 100: 300}


def utc():
    """Current UTC time as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def post(batch, index):
    """Post one bid that will be judged and recorded, even if it does not lead."""
    body = json.dumps({
        "lot_id": "003",
        "bidder": f"e2e{batch}-{index}",
        "amount": 100,
        "seen_price": 280,
    })
    started = time.perf_counter()
    sent = utc()
    text = ""
    ok = False
    try:
        completed = subprocess.run(
            ["curl", "-sS", "-m", "90", "-w", "\n%{http_code}", "-X", "POST", URL,
             "-H", "Content-Type: application/json", "-d", body],
            check=False, capture_output=True, text=True, timeout=100,
        )
        lines = completed.stdout.strip().splitlines()
        code = lines[-1] if lines else ""
        text = "\n".join(lines[:-1]) if len(lines) > 1 else ""
        ok = code == "200" and text.startswith("Queued bid ")
    except Exception as error:
        text = str(error)
    bid_id = text.replace("Queued bid ", "").strip() if ok else ""
    return {
        "batch": batch,
        "sent_utc": sent,
        "http_s": round(time.perf_counter() - started, 3),
        "ok": int(ok),
        "bid_id": bid_id,
    }


def write_query(rows):
    """Build one log query that reports completion time for each batch."""
    parts = []
    for batch in (1, 5, 10, 20, 50, 100):
        ids = [row["bid_id"] for row in rows if row["batch"] == batch and row["ok"] and row["bid_id"]]
        if not ids:
            continue
        quoted = ", ".join('"' + bid_id + '"' for bid_id in ids)
        parts.append(f'bid in ({quoted}), "{batch}"')
    case_body = ",\n    ".join(parts + ['"other"'])
    query = f"""let queued = traces
| where timestamp > datetime(2026-11-03T02:00:00Z)
| where message startswith "Queued bid "
| extend bid = extract(@"Queued bid ([0-9a-z-]+)", 1, message)
| summarize queued_at = min(timestamp) by bid;
let done = traces
| where timestamp > datetime(2026-11-03T02:00:00Z)
| where message has "recorded as"
| extend bid = extract(@"([0-9]{{8}}-[0-9]{{6}}-[0-9a-z]+) recorded as", 1, message)
| summarize done_at = min(timestamp) by bid;
queued
| join kind=inner done on bid
| extend seconds = 1.0 * datetime_diff("Millisecond", done_at, queued_at) / 1000
| extend batch = case(
    {case_body})
| where batch != "other"
| summarize bids=count(), median_s=percentile(seconds, 50), p95_s=percentile(seconds, 95), slowest_s=max(seconds), fastest_s=min(seconds) by batch
| order by toint(batch) asc
"""
    with open(QUERY, "w") as handle:
        handle.write(query)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = []
    print("batch\tstart_utc\tend_utc\tok\tfailed", flush=True)
    for batch in (1, 5, 10, 20, 50, 100):
        start = utc()
        with ThreadPoolExecutor(max_workers=batch) as pool:
            got = list(pool.map(lambda index: post(batch, index), range(batch)))
        end = utc()
        rows.extend(got)
        failed = sum(1 for row in got if not row["ok"])
        print(f"{batch}\t{start}\t{end}\t{batch - failed}\t{failed}", flush=True)
        print(f"pause {PAUSES[batch]}s", flush=True)
        time.sleep(PAUSES[batch])
    with open(OUT, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    write_query(rows)
    print("DONE", flush=True)
    print(QUERY, flush=True)


if __name__ == "__main__":
    main()
