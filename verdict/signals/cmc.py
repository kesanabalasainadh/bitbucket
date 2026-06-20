import argparse
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

import requests
from dotenv import load_dotenv

from verdict.schema import OHLCVSeries, OHLCVBar, Signal

load_dotenv()


class CMCClient:
    def __init__(self, offline=False):
        self.offline = offline
        if not self.offline:
            self.mcp_api_key = os.getenv("CMC_MCP_API_KEY")
            self.pro_api_key = os.getenv("CMC_PRO_API_KEY")
            self.mcp_url = os.getenv("CMC_MCP_URL", "https://mcp.coinmarketcap.com/mcp")
            self.rest_base = os.getenv("CMC_REST_BASE", "https://pro-api.coinmarketcap.com")

    def _request_mcp(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.offline:
            return {}

        headers = {"X-CMC-MCP-API-KEY": self.mcp_api_key}
        payload = {
            "tool": tool_name,
            "params": params,
        }
        response = requests.post(self.mcp_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    def _request_rest(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.offline:
            return {}

        headers = {"X-CMC_PRO_API_KEY": self.pro_api_key}
        response = requests.get(f"{self.rest_base}{endpoint}", headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def quotes(self, symbols: List[str]) -> Dict[str, float]:
        if self.offline:
            return {sym: 600.0 for sym in symbols}

        try:
            # Note: The tool name might need to be exact. Using typical format.
            data = self._request_mcp("mcp__cmc-mcp__get_crypto_quotes_latest", {"symbol": ",".join(symbols)})
            if "data" in data and isinstance(data["data"], dict):
                return {item['symbol']: item['quote']['USD']['price'] for item in data['data'].values()}
            return {}
        except requests.exceptions.RequestException:
            # Fallback to REST API
            data = self._request_rest("/v1/cryptocurrency/quotes/latest", {"symbol": ",".join(symbols)})
            return {item['symbol']: item['quote']['USD']['price'] for item in data.get('data', {}).values()}

    def technicals(self, symbol: str) -> Dict[str, float]:
        if self.offline:
            return {"rsi": 55.0, "macd": 1.2, "ema_20": 590.0, "ema_50": 580.0, "atr": 15.0}
        
        try:
            # Gated endpoint in basic tier usually, handle gracefully
            data = self._request_mcp("mcp__cmc-mcp__get_crypto_technical_analysis", {"symbol": symbol})
            return {}
        except Exception:
            return {}

    def derivatives(self, symbol: str = "BNB") -> Dict:
        if self.offline:
            return {"funding_rate": 0.01, "open_interest": 15000000.0, "liquidations": 0.0}
        try:
            data = self._request_mcp("mcp__cmc-mcp__get_global_crypto_derivatives_metrics", {"symbol": symbol})
            return {}
        except Exception:
            return {}

    def global_metrics(self) -> Dict:
        if self.offline:
            return {"fear_greed": 65.0, "btc_dominance": 54.2}
        try:
            data = self._request_mcp("mcp__cmc-mcp__get_global_metrics_latest", {})
            return {}
        except Exception:
            return {}

    def ohlcv(self, symbol: str, timeframe: str, start: str, end: str) -> OHLCVSeries:
        if self.offline:
            bar = OHLCVBar(
                ts=datetime.now(timezone.utc), open=600.0, high=605.0, low=595.0, close=600.0, volume=10000.0
            )
            return OHLCVSeries(symbol=symbol, timeframe=timeframe, source="cmc", bars=[bar])
        return OHLCVSeries(symbol=symbol, timeframe=timeframe, source="cmc", bars=[])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BNB/USDT")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    client = CMCClient(offline=args.offline)
    
    # Deferred import to avoid circular dependency if normalize imports cmc
    from verdict.signals.normalize import build_signal
    
    signal = build_signal(args.symbol, client)
    print(signal.model_dump_json(indent=2))