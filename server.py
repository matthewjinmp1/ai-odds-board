#!/usr/bin/env python3
"""Serve the AI Odds Board on http://localhost:3003.

Static files come from ai-dashboard/. One extra endpoint fills a gap in Polymarket's
public API: /api/valuation?slug=<event-slug> returns the current private-market
valuation (Nasdaq Private Market data) that Polymarket shows on "valuation hit" event
pages. It is only embedded in the page HTML, so we fetch the page and pull it out.
"""
from __future__ import annotations

import json
import re
import threading
import time
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
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
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


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(ROOT)))
    print(f"AI Odds Board on http://localhost:{PORT}")
    server.serve_forever()
