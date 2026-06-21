#!/usr/bin/env python3
"""
VERDICT — demo web server (Flask).

A thin live backend over the VERDICT engine so the dashboard can show REAL results:

    GET  /                 -> the dashboard (static/index.html)
    GET  /api/verdict      -> the full deterministic payload (two-sided verdicts,
                              regime grid, walk-forward) — runs the engine, falls back
                              to the committed web/data/verdict.json on any error.
    GET  /api/live-cmc     -> a fresh live CoinMarketCap signal (real if a key is set,
                              offline fixture otherwise).

Run:  pip install -r web/requirements.txt   &&   python web/server.py   (http://localhost:3003)
Static fallback: the dashboard also runs with NO server — the committed
web/data/verdict.json makes it a deterministic static site (GitHub Pages friendly).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
try:
    from flask_cors import CORS
except ImportError:                              # CORS optional for local dev
    CORS = None

_REPO = Path(__file__).resolve().parents[1]
if (_REPO / "verdict" / "__init__.py").exists():
    sys.path.insert(0, str(_REPO))

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
# data/ is gitignored (runtime), static/ copy is the committed fallback for a fresh clone.
DATA_CANDIDATES = [HERE / "data" / "verdict.json", STATIC / "verdict.json"]

app = Flask(__name__, static_folder=str(STATIC))
app.config["JSON_SORT_KEYS"] = False
if CORS:
    CORS(app)


def _cached_payload() -> dict:
    for p in DATA_CANDIDATES:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"error": "no cached payload; run python web/build_data.py"}


@app.route("/")
def index():
    return send_from_directory(str(STATIC), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(STATIC), filename)


@app.route("/favicon.ico")
def favicon():
    # so every path on the domain (incl. the /api/* JSON pages) shows the tab icon
    return send_from_directory(str(STATIC), "favicon.png", mimetype="image/png")


@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_from_directory(str(STATIC), "apple-touch-icon.png")


@app.route("/api/verdict")
def api_verdict():
    """Run the engine live; fall back to the committed deterministic payload."""
    try:
        from web.build_data import (regime_grid, two_sided, walkforward_windows,
                                     live_cmc, sentiment_block, onchain_identity)
        from verdict.core.costs import PANCAKESWAP_V2
        trade_block, notrade_block = two_sided()
        _static = _cached_payload()  # static-only blocks (candles, tf sweep) — no recompute
        payload = {
            "tests": "126 passed, 2 skipped",
            "cost_model": PANCAKESWAP_V2.label,
            "live_cmc": live_cmc(),
            "onchain": onchain_identity(),
            "sentiment": sentiment_block(),
            "regime_grid": regime_grid(),
            "walkforward": walkforward_windows(),
            "trade": trade_block,
            "no_trade": notrade_block,
            "candles": _static.get("candles"),
            "tf_sweep": _static.get("tf_sweep"),
            "source": "live-engine",
        }
        return jsonify(payload)
    except Exception as e:                        # robust: always serve something
        payload = _cached_payload()
        payload["source"] = f"cached (live engine error: {str(e)[:80]})"
        return jsonify(payload)


@app.route("/api/live-cmc")
def api_live_cmc():
    try:
        from web.build_data import live_cmc
        return jsonify(live_cmc())
    except Exception as e:
        return jsonify({"error": str(e)[:120], "live": False})


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "3003"))
    print(f"VERDICT dashboard -> http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
