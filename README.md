# AI Odds Board

A local dashboard of live AI-related [Polymarket](https://polymarket.com) markets: model release dates, AI IPOs, valuations, benchmarks and more. Groups of related bets (e.g. "released by Oct 24 / Oct 31 / Dec 31") are condensed into a single best-guess number.

Data comes straight from Polymarket's free public Gamma API in the browser. No API key and no build step; refreshes every 60 seconds.

## Run

```bash
./start.sh
```

Then open http://localhost:3003.

Or without the script:

```bash
python3 -m http.server 3003 --directory ai-dashboard
```

## How the best guesses work

- **"By date" ladders** (each market = P(happens by date)): treated as a cumulative distribution; the best guess is the date where it crosses 50%.
- **"On which day/month" buckets**: probabilities normalized, then the median date.
- **Threshold ladders** ("valuation hit ↑$2T", "score 60%+"): P(value ≥ x) interpolated to the 50% point.
- **Numeric buckets** ("$1.5–$1.75T", "<500B", "3"): median (or expected value for single numbers), conditioned on the event happening.
- **"Which of these will happen"** lists: expected count (sum of probabilities).
- **"Who wins"** lists: the current leader.
