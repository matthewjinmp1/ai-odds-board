# AI Odds Board

A local dashboard of live AI-related [Polymarket](https://polymarket.com) markets: model release dates, AI IPOs, valuations, benchmarks and more. Groups of related bets (e.g. "released by Oct 24 / Oct 31 / Dec 31") are condensed into a single best-guess number.

Market data comes from Polymarket's free public Gamma API (no API key, no build step) and refreshes every 60 seconds. Current private valuations (Nasdaq Private Market data shown on Polymarket's "valuation hit" pages) aren't in the public API, so `server.py` reads them from those pages and caches them for 15 minutes.

## Run

```bash
./start.sh
```

Then open http://localhost:3003.

Or directly:

```bash
python3 server.py
```

Needs only Python 3's standard library.

## How the best guesses work

- **"By date" ladders** (each market = P(happens by date)): treated as a cumulative distribution; the best guess is the date where it crosses 50%.
- **"On which day/month" buckets**: probabilities normalized, then the median date.
- **Threshold ladders** ("valuation hit ↑$2T", "score 60%+"): P(value ≥ x) interpolated to the 50% point.
- **Numeric buckets** ("$1.5–$1.75T", "<500B", "3"): median (or expected value for single numbers), conditioned on the event happening.
- **"Which of these will happen"** lists: expected count (sum of probabilities).
- **"Who wins"** lists: the current leader.

## Confidence score

Every best guess shows a confidence from 0–100% (hover it for the breakdown):

```
confidence = coverage × √data × √volume × √tightness × consistency
```

- **Coverage**: 1 if the 50% point lies inside the listed bets. If extrapolated, `√(share of the way to 50% the prices reach × 1/(1 + extrapolated distance / span of the data))`. Lower when most money says the event won't happen (e.g. "No IPO") or the median lands in an open-ended bucket.
- **Data**: `n/(n+1)` for `n` price points.
- **Volume**: `0.2·log10(volume) − 0.3`, clamped to 0.1–1 ($10k → 50%, $1M → 90%).
- **Tightness**: `1/(1 + 50% range width / scale)`; scale is time until the guess (min 30 days) for dates, half the value for numbers.
- **Consistency**: `1 −` probability that had to be corrected because prices contradicted each other.
