from datetime import datetime, timezone

from verdict.schema import Signal
from verdict.signals.cmc import CMCClient


def get_regime(fear_greed: float, btc_dominance: float) -> str:
    if fear_greed is None:
        return "neutral"
    if fear_greed >= 70:
        return "risk_on"
    elif fear_greed <= 30:
        return "risk_off"
    return "neutral"


def build_signal(symbol: str, client: CMCClient) -> Signal:
    base_symbol = symbol.split('/')[0]
    
    quotes = client.quotes([base_symbol])
    price = quotes.get(base_symbol, 0.0)
    
    technicals = client.technicals(base_symbol)
    derivatives = client.derivatives(base_symbol)
    global_metrics = client.global_metrics()
    
    fear_greed = global_metrics.get("fear_greed")
    btc_dominance = global_metrics.get("btc_dominance")
    
    regime = get_regime(fear_greed, btc_dominance)
    
    return Signal(
        ts=datetime.now(timezone.utc),
        symbol=symbol,
        price=price,
        indicators=technicals,
        funding_rate=derivatives.get("funding_rate"),
        open_interest=derivatives.get("open_interest"),
        fear_greed=fear_greed,
        btc_dominance=btc_dominance,
        regime=regime,
        narratives=[],
        source="cmc-mcp"
    )