#!/usr/bin/env python3
"""Serve the AI Odds Board on http://localhost:3003.

Static files come from ai-dashboard/. Two extra endpoints:

- /api/valuation?slug=<event-slug> fills a gap in Polymarket's public API: the current
  private-market valuation (Nasdaq Private Market data) that Polymarket shows on "valuation
  hit" event pages. It is only embedded in the page HTML, so we fetch the page and pull it out.
- /api/kalshi returns Kalshi's open AI markets, reshaped like Polymarket events so the board
  treats both the same. Kalshi's public API doesn't allow browser requests (no CORS) and needs
  one call per series, so a background thread gathers them every 10 minutes.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 3003
ROOT = Path(__file__).resolve().parent / "ai-dashboard"
CACHE_SECONDS = 15 * 60
SLUG_RE = re.compile(r"^[a-z0-9-]{1,200}$")

_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def fetch_valuation(slug: str) -> dict | None:
    req = urllib.request.Request(
        f"https://polymarket.com/event/{slug}",
        headers={"User-Agent": "Mozilla/5.0 (ai-odds-board local dashboard)"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", "replace")
    # The data sits in the Next.js payload as escaped JSON: {\"isHitMarket\":true,...}
    text = html.replace('\\"', '"')
    start = text.find('{"isHitMarket":')
    if start == -1:
        return None
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    if not obj.get("currentValuation"):
        return None
    history = [[p["time"], p["close"]] for p in obj.get("data", []) if p.get("close")]
    return {
        "company": obj.get("companyName"),
        "current": obj["currentValuation"],
        "history": history,
        "source": obj.get("sourceUrl"),
        "asOf": obj.get("endDate"),
    }


def get_valuation(slug: str) -> dict | None:
    now = time.time()
    with _lock:
        hit = _cache.get(slug)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        value = fetch_valuation(slug)
    except Exception as e:  # network or parse failure: serve stale data if we have it
        print(f"valuation fetch failed for {slug}: {e}")
        return hit[1] if hit else None
    with _lock:
        _cache[slug] = (now, value)
    return value


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Make browsers revalidate the page, so an update shows on the next load.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/kalshi":
            with _lock:
                body = json.dumps(_kalshi).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        if url.path != "/api/valuation":
            return super().do_GET()
        slug = urllib.parse.parse_qs(url.query).get("slug", [""])[0]
        if not SLUG_RE.match(slug):
            return self.send_error(400, "bad slug")
        body = json.dumps(get_valuation(slug)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_REFRESH = 10 * 60
KALSHI_PAUSE = 0.3  # between requests; Kalshi rate-limits bursts
KALSHI_CATEGORIES = ["Science and Technology", "Companies", "Financials", "Economics", "Politics"]
# A series counts as AI if its title mentions one of these (Kalshi has no AI category to speak of).
KALSHI_AI = re.compile(r"\b(ai|a\.i\.|agi|openai|anthropic|claude|fable|chatgpt|gpt|gemini|deepmind|grok|xai|llama|"
                       r"deepseek|qwen|mistral|kimi|llms?|artificial intelligence|superintelligence|nvidia|"
                       r"data centers?|humanoid|robotaxi|waymo|optimus|perplexity|cursor|anysphere|mythos|astra)\b", re.I)
_kalshi = {"events": [], "updated": None, "error": None}


def kalshi_get(path: str):
    for attempt in range(5):
        req = urllib.request.Request(KALSHI_API + path, headers={"Accept": "application/json", "User-Agent": "ai-odds-board/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Kalshi kept rate-limiting")


def kalshi_price(m: dict) -> float | None:
    """Yes probability: the bid/ask midpoint when the book is tight, else the last trade."""
    num = lambda k: float(m.get(k) or 0)
    bid, ask, last = num("yes_bid_dollars"), num("yes_ask_dollars"), num("last_price_dollars")
    if 0 < ask and ask - bid <= 0.2:
        return (bid + ask) / 2
    return last if last > 0 else None


def kalshi_label(label: str) -> str:
    """Kalshi words date ladders as "Before Feb 1, 2027" / "Before 2030"; the page reads Polymarket's
    "by" style, so give the last day that counts instead ("Jan 31, 2027", "Dec 31, 2029")."""
    from datetime import datetime, timedelta
    m = re.match(r"^before\s+(.+)$", label.strip(), re.I)
    if not m:
        return label
    rest = m.group(1).strip()
    if re.fullmatch(r"\d{4}", rest):
        return f"Dec 31, {int(rest) - 1}"
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            day = datetime.strptime(rest, fmt) - timedelta(days=1)
            return f"{day:%b} {day.day}, {day.year}"
        except ValueError:
            pass
    return label


def kalshi_event(e: dict) -> dict | None:
    """A Kalshi event in the shape of a Polymarket gamma event (what the page's prepare() reads)."""
    markets = []
    for m in e.get("markets", []):
        p = kalshi_price(m)
        if p is None or m.get("status") not in ("active", "open"):
            continue
        contracts = float(m.get("volume_fp") or 0)
        prev = float(m.get("previous_price_dollars") or 0)
        markets.append({
            "question": m.get("title") or e["title"],
            "groupItemTitle": kalshi_label(m.get("yes_sub_title") or m.get("subtitle") or m.get("title") or ""),
            "outcomes": '["Yes","No"]',
            "outcomePrices": json.dumps([str(p), str(1 - p)]),
            "oneDayPriceChange": p - prev if prev > 0 else 0,
            # Kalshi counts contracts ($1 payout each); contracts × price approximates dollars traded.
            "volume": contracts * p,
            "volume24h": float(m.get("volume_24h_fp") or 0) * p,
            "endDate": m.get("close_time"),
            "active": True,
            "closed": False,
        })
    if not markets:
        return None
    series = e["series_ticker"]
    return {
        "id": f"kalshi:{e['event_ticker']}",
        "title": e["title"],
        "slug": e["event_ticker"].lower(),
        "url": f"https://kalshi.com/markets/{series.lower()}",
        "source": "kalshi",
        "volume": sum(m["volume"] for m in markets),
        "volume24hr": sum(m["volume24h"] for m in markets),
        "endDate": e.get("strike_date") or max((m["endDate"] for m in markets if m["endDate"]), default=None),
        "negRisk": bool(e.get("mutually_exclusive")),
        "markets": markets,
    }


def refresh_kalshi() -> None:
    series = []
    for category in KALSHI_CATEGORIES:
        series += kalshi_get("/series?category=" + urllib.parse.quote(category)).get("series") or []
        time.sleep(KALSHI_PAUSE)
    tickers = sorted({x["ticker"] for x in series if KALSHI_AI.search(x.get("title") or "")})
    events = []
    for ticker in tickers:
        page = kalshi_get(f"/events?series_ticker={ticker}&status=open&with_nested_markets=true&limit=100")
        events += [ev for ev in (kalshi_event(e) for e in page.get("events", [])) if ev]
        time.sleep(KALSHI_PAUSE)
    with _lock:
        _kalshi.update(events=events, updated=time.time(), error=None)
    print(f"Kalshi: {len(events)} open AI events from {len(tickers)} series", flush=True)


def kalshi_loop() -> None:
    while True:
        try:
            refresh_kalshi()
        except Exception as e:  # keep serving the last good list
            with _lock:
                _kalshi["error"] = str(e)
            print(f"Kalshi refresh failed: {e}", flush=True)
        time.sleep(KALSHI_REFRESH)


if __name__ == "__main__":
    threading.Thread(target=kalshi_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(ROOT)))
    print(f"AI Odds Board on http://localhost:{PORT}")
    server.serve_forever()
