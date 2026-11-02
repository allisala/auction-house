# The Auction House

I built a small auction for three strange objects. A Victorian pocket watch, a painting of a room with no door, and a typewriter that still travels. The objects are made up. The problem is not.

Several people try to change the same price at nearly the same moment. The house has to reject a bid that is too low, reject a bid that arrives after the deadline, and still end with one leader. Two bidders must not both be written down as the winner.

![Lot 001 is a pocket watch at £120. Lot 002 is a painting at £500. Lot 003 is a typewriter at £80.](figures/lots.png)

| Lot | Object | Opens at | Minimum rise |
| --- | --- | --- | --- |
| 001 | Victorian Pocket Watch, no. 14, still ticking | £120 | £10 |
| 002 | Room With No Door, oil, unsigned | £500 | £25 |
| 003 | The Travelling Remington, 1934 | £80 | £5 |

The question I want the system to answer is: what happens to the price, and to the losers, when more and more bids hit one lot at the same time?

## What has to stay true

- A bid below the current price plus the minimum rise is rejected.
- A bid that the server received after the deadline is rejected. I use the server time, not the clock on the bidder's laptop.
- Two updates of the same lot cannot both land. The write carries the version I just read. If that version has already moved, the write fails, I read the lot again, and I judge the bid against the new price.
- One lot has one leader and one highest bid.
- Every bid id is remembered. A second delivery of the same message does not raise the price twice.
- Accepted and rejected bids can be read back afterwards.

## How a bid moves

![The bidder calls receive_bid. A queue starts process_bid. A second queue starts record_result.](figures/workflow.png)

The functions do not call each other. Each queue message is an id and a file name. The bid itself sits in blob storage.

| Place | What is stored |
| --- | --- |
| `auction/requests/<bid_id>.json` | The bid function 1 accepted for checking. |
| Queue `incoming-bids` | The id and the request file name. This starts function 2. |
| `auction/lots/<lot_id>.json` | The price, the leader, the version, and the bids already judged. |
| Queue `bid-results` | The id and the decision file name. This starts function 3. |
| `auction/results/<bid_id>.json` | Accepted or rejected, and why. |

**1. receive_bid.** HTTP, `POST /api/bids`. I send `lot_id`, `bidder`, and `amount`. The function checks the shape, stamps the bid with the server time, writes the request, and queues a pointer. The reply is `Queued bid <id>`. That reply does not mean the bid won.

```json
{
  "lot_id": "001",
  "bidder": "Bob",
  "amount": 180,
  "seen_price": 120
}
```

`seen_price` is the price the bidder thought was current. I use it only to tell two kinds of loss apart: too low from the start, or outbid while the bid was waiting.

**2. process_bid.** Queue trigger on `incoming-bids`. It reads the lot and the etag. If this bid id is already on the lot, it keeps the old decision. Otherwise it judges the bid and writes the lot back only if the etag still matches. Azure calls that an `If-Match` write. A clash raises `ResourceModifiedError`. I try again, up to 80 times, against the price I just reread. Then it queues the decision.

**3. record_result.** Queue trigger on `bid-results`. It writes `results/<bid_id>.json`. A repeat delivery overwrites that same file.

## Three people, one watch

The watch opens at £120. Alice bids £150, Bob bids £180, Charlie bids £160. All three saw £120, and all three would be legal at the opening price.

Taken in that order, Alice is accepted, Bob replaces her, and Charlie is rejected. £160 is no longer enough once the book says £180.

![The pocket watch moves from £120 to £150 to £180. Charlie is rejected.](figures/pocket_watch.png)

The other order is Charlie, then Alice, then Bob. Charlie is accepted, Alice is rejected, and Bob still finishes as the leader on £180. Who gets a "yes" along the way depends on the order. The final leader does not have to be the person whose HTTP call arrived last.

The full two tables are in [walkthrough/pocket_watch.md](walkthrough/pocket_watch.md). Running Bob's bid a second time leaves the price at £180.

## The last minute

The deadline in these runs is 18:00:00 UTC on 3 November 2026. Mina, Owen, and Priya bid in the last 30 seconds. Sam and Noor bid higher, but the server time is already past 18:00, so they are late. Priya keeps the watch at £310. A larger bid does not win after the deadline.

![Five bids at the end of the pocket watch. The two after 18:00 are late.](figures/last_second.png)

| Bidder | Bid | Server time | Result |
| --- | --- | --- | --- |
| Mina | £200 | 17:59:31 | accepted |
| Owen | £260 | 17:59:44 | accepted |
| Priya | £310 | 17:59:58 | accepted |
| Sam | £400 | 18:00:01 | late |
| Noor | £450 | 18:00:06 | late |

## One lot, or twenty

I then threw the same kind of bid at the rules from several threads at once. Every bidder had seen £120 and offered at least one minimum rise above it, so a loss means the price moved, not that the bid was silly at the start. One run puts every bid on the pocket watch. The other spreads them across 20 lots. These numbers are from my laptop, with threads standing in for concurrent function executions. I have not deployed this house to Azure yet. A second run can move the clash count a little, because the threads race. The decision rules do not move.

![Failed compare-and-swap attempts. One lot climbs at 500 and 1000 bids. Twenty lots stay low.](figures/contention.png)

| Bids together | One lot, seconds | One lot, clashes | One lot, gave up | Twenty lots, seconds | Twenty lots, clashes |
| --- | --- | --- | --- | --- | --- |
| 10 | 0.003 | 9 | 0 | 0.001 | 0 |
| 50 | 0.005 | 0 | 0 | 0.002 | 0 |
| 100 | 0.019 | 0 | 0 | 0.004 | 0 |
| 500 | 0.914 | 511 | 0 | 0.030 | 0 |
| 1,000 | 15.072 | 8,052 | 81 | 0.127 | 265 |

On one lot, 1,000 bids took about 15 seconds and 81 bids gave up after 80 failed writes. Spread over 20 lots, the same 1,000 bids took about 0.13 seconds and nobody gave up. The fight is not "how many bids exist". The fight is how many of them want the same stored price.

![On the pocket watch, most bids are outbid while they wait. At 1,000 bids, some give up.](figures/outcomes.png)

At 1,000 bids on the watch, 3 were accepted, 916 were outbid while waiting, and 81 were given up. The stored price still reached the highest offer in the batch, £520. The cap on retries is what creates the failures. Without that cap the function would keep rereading. With it, a bid can be abandoned so the rest of the auction can move.

![Time until every bid has a decision. One lot pulls away from twenty lots.](figures/latency.png)

The useful comparison is the popular lot against the quiet rooms. A last-second rush on one object is where the version checks, the retries, and the abandoned bids show up.

## Where the files are

```text
auction-house/
├── function_app.py     receive_bid, process_bid, record_result
├── auction.py          the price rules and the compare-and-swap
├── host.json
├── requirements.txt
├── scripts/            the laptop run that drew the pictures
├── figures/            the pictures
├── results/            the tables from that run
└── walkthrough/        Alice, Bob, and Charlie
```

| File | What it is |
| --- | --- |
| [function_app.py](function_app.py) | The three Azure functions. |
| [auction.py](auction.py) | Judging a bid, and the in-memory version check. |
| [scripts/make_figures.py](scripts/make_figures.py) | Runs the batches and writes the pictures. |
| [figures/](figures/) | Lots, workflow, the watch, contention, outcomes, latency. |
| [results/](results/) | The csv tables behind the pictures. |
| [walkthrough/pocket_watch.md](walkthrough/pocket_watch.md) | The two orders of Alice, Bob, and Charlie. |

The function files stay in this folder so the folder can be deployed as one Function App. The pictures and the scripts are not part of that deploy.

To draw the pictures again I use the laptop environment that has matplotlib:

```bash
python3 scripts/make_figures.py
```
