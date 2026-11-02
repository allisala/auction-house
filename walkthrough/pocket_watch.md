# Pocket watch, three bids

The lot opens at £120. The minimum rise is £10. Alice, Bob, and Charlie all saw £120.

If I take them in the order Alice, Bob, Charlie:

| Bidder | Bid | Result | Highest after |
| --- | --- | --- | --- |
| Alice | £150 | accepted | £150 |
| Bob | £180 | accepted | £180 |
| Charlie | £160 | outbid | £180 |

Charlie's £160 would have been enough at the start. It is not enough once Bob is on the book. Bob is the only leader at the end.

If the same three bids are taken as Charlie, Alice, Bob:

| Bidder | Bid | Result | Highest after |
| --- | --- | --- | --- |
| Charlie | £160 | accepted | £160 |
| Alice | £150 | outbid | £160 |
| Bob | £180 | accepted | £180 |

Alice is rejected in this order, and Charlie is accepted. The leader is still Bob, on £180. The winner is not whoever's HTTP call arrived last. It is whoever still holds the price after every bid has been judged.

Sending Bob's bid through the rules a second time leaves the price at £180. The same bid id is already on the lot, so the retry does not raise the price again.
