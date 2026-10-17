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
