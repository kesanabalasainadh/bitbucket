"""
verdict.core.data — candle loader for the VERDICT backtest engine.

Design goals (all serve the Track-2 reproducibility + determinism requirement):
  * OFFLINE-FIRST: by default we read committed CSV-gz fixtures under
    ``verdict/core/_fixtures/candles/`` so a judge reproduces identical numbers
    from a clean clone with NO network and NO API key.
  * REFRESHABLE: ``source="ccxt"`` + ``refresh=True`` pulls fresh OHLCV from a
    public exchange (kucoin by default — Binance.com is geo-blocked in some
    regions) and rewrites the fixture + a parquet runtime cache.
  * NO NETWORK AT IMPORT: the only I/O is inside ``load_ohlcv``.

Public contract (see ../CONTRACTS.md):
    load_ohlcv(symbol, timeframe, start, end, source="cmc") -> OHLCVSeries

``source`` selects the *refresh backend* when a fetch is needed; the committed
fixture is always preferred for reproducibility unless ``refresh=True``.
"""
from __future__ import annotations

import gzip
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from verdict.schema import OHLCVBar, OHLCVSeries

# Committed, reproducible candle data (csv.gz — small, diffable, offline).
FIXTURE_DIR = Path(__file__).resolve().parent / "_fixtures" / "candles"
# Regenerable runtime cache (gitignored parquet under repo data/).
RUNTIME_CACHE = Path(__file__).resolve().parents[2] / "data" / "candles"

_COLS = ("ts", "open", "high", "low", "close", "volume")

Fetcher = Callable[[str, str, Optional[datetime], Optional[datetime]], OHLCVSeries]
WhenT = Union[datetime, str, None]


def _sanitize(symbol: str) -> str:
    return symbol.replace("/", "-").replace(":", "-")


def fixture_path(symbol: str, timeframe: str, fixture_dir: Path = FIXTURE_DIR) -> Path:
    return Path(fixture_dir) / f"{_sanitize(symbol)}_{timeframe}.csv.gz"


def _as_utc(when: WhenT) -> Optional[datetime]:
    if when is None:
        return None
    if isinstance(when, str):
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Fixture I/O (pure, offline)
# --------------------------------------------------------------------------- #
def _write_candles(series: OHLCVSeries, path: Path) -> None:
    """Persist a series as gzipped CSV. ts is ISO-8601 UTC; lossless for OHLCV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bars = sorted(series.bars, key=lambda b: b.ts)
    lines = [",".join(_COLS)]
    for b in bars:
        ts = b.ts.astimezone(timezone.utc).isoformat()
        lines.append(
            f"{ts},{b.open!r},{b.high!r},{b.low!r},{b.close!r},{b.volume!r}"
        )
    text = "\n".join(lines) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)


def _read_candles(symbol: str, timeframe: str, path: Path) -> OHLCVSeries:
    with gzip.open(Path(path), "rt", encoding="utf-8") as fh:
        rows = fh.read().splitlines()
    if not rows:
        return OHLCVSeries(symbol=symbol, timeframe=timeframe, bars=[])
    header, body = rows[0].split(","), rows[1:]
    idx = {name: header.index(name) for name in _COLS}
    bars: list[OHLCVBar] = []
    for line in body:
        if not line.strip():
            continue
        parts = line.split(",")
        ts = datetime.fromisoformat(parts[idx["ts"]])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bars.append(
            OHLCVBar(
                ts=ts.astimezone(timezone.utc),
                open=float(parts[idx["open"]]),
                high=float(parts[idx["high"]]),
                low=float(parts[idx["low"]]),
                close=float(parts[idx["close"]]),
                volume=float(parts[idx["volume"]]),
            )
        )
    bars.sort(key=lambda b: b.ts)
    # Honest provenance: the committed candle fixtures are sourced from a public
    # exchange via ccxt (kucoin) — NOT CoinMarketCap. CMC powers the live
    # signal/regime layer (verdict/signals/), not the raw historical OHLCV.
    return OHLCVSeries(symbol=symbol, timeframe=timeframe, source="ccxt-kucoin", bars=bars)


def _slice(series: OHLCVSeries, start: Optional[datetime], end: Optional[datetime]) -> OHLCVSeries:
    bars = sorted(series.bars, key=lambda b: b.ts)
    if start is not None:
        bars = [b for b in bars if b.ts >= start]
    if end is not None:
        bars = [b for b in bars if b.ts <= end]
    return OHLCVSeries(symbol=series.symbol, timeframe=series.timeframe,
                       source=series.source, bars=bars)


# --------------------------------------------------------------------------- #
# Public loader
# --------------------------------------------------------------------------- #
def load_ohlcv(
    symbol: str,
    timeframe: str,
    start: WhenT = None,
    end: WhenT = None,
    source: str = "cmc",
    *,
    fixture_dir: Path = FIXTURE_DIR,
    refresh: bool = False,
    fetcher: Optional[Fetcher] = None,
) -> OHLCVSeries:
    """Load OHLCV for ``symbol``/``timeframe``, sliced to ``[start, end]``.

    Offline-first: prefers the committed fixture. Only fetches when the fixture
    is absent or ``refresh=True``. ``source`` chooses the fetch backend
    (``"ccxt"`` -> public exchange); ``"cmc"`` is reserved for WP-3's CMC OHLCV.
    """
    start_dt, end_dt = _as_utc(start), _as_utc(end)
    path = fixture_path(symbol, timeframe, fixture_dir)

    # Offline-first: a present fixture wins unless an explicit refresh is asked.
    if path.exists() and not refresh:
        return _slice(_read_candles(symbol, timeframe, path), start_dt, end_dt)

    # Need to fetch. Only do so on an explicit opt-in (refresh or a fetcher) —
    # never auto-hit the network just because a fixture is missing.
    if not (refresh or fetcher is not None):
        raise FileNotFoundError(
            f"no candle fixture at {path}; pass refresh=True to fetch it live"
        )

    fetch = fetcher
    if fetch is None:
        if source not in ("ccxt", "cmc", "auto"):
            raise ValueError(f"unknown source {source!r}")
        fetch = _fetch_ccxt
    series = fetch(symbol, timeframe, start_dt, end_dt)
    _write_candles(series, path)
    return _slice(series, start_dt, end_dt)


# --------------------------------------------------------------------------- #
# Live fetch backend (the I/O boundary — exercised when generating fixtures)
# --------------------------------------------------------------------------- #
def _fetch_ccxt(
    symbol: str,
    timeframe: str,
    start: Optional[datetime],
    end: Optional[datetime],
    exchange_id: str = "kucoin",
) -> OHLCVSeries:
    """Paginate public OHLCV from a ccxt exchange into an OHLCVSeries."""
    import ccxt  # local import: no network/deps at module import

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": 20000})
    ex.load_markets()
    if timeframe not in (ex.timeframes or {}):
        raise ValueError(f"{exchange_id} has no timeframe {timeframe!r}")

    since = int((start or datetime(2021, 1, 1, tzinfo=timezone.utc)).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000) if end else None
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    rows: list[list] = []
    seen: set[int] = set()
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1500)
        batch = [r for r in batch if r[0] not in seen]
        if not batch:
            break
        for r in batch:
            seen.add(r[0])
        rows.extend(batch)
        last = batch[-1][0]
        since = last + tf_ms
        if end_ms and last >= end_ms:
            break
        if len(batch) < 1500:
            break

    bars = [
        OHLCVBar(
            ts=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
            open=float(r[1]), high=float(r[2]), low=float(r[3]),
            close=float(r[4]), volume=float(r[5]),
        )
        for r in sorted(rows, key=lambda r: r[0])
        if (end_ms is None or r[0] <= end_ms)
    ]
    return OHLCVSeries(symbol=symbol, timeframe=timeframe,
                       source=f"ccxt-{exchange_id}", bars=bars)
