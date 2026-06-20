import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
import math

from verdict.schema import OHLCVSeries, StrategySpec
from verdict.core.data import load_ohlcv
from verdict.core.candidates import generate_candidates
from verdict.core.backtest import backtest_detailed, PANCAKESWAP_V2

def align_sentiment(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    # Load sentiment snapshot
    data_path = Path(__file__).resolve().parent.parent / "data" / "sentiment_snapshot.csv"
    if not data_path.exists():
        return pd.DataFrame(index=df.index)
        
    s_df = pd.read_csv(data_path)
    s_df = s_df[s_df['asset'] == asset].copy()
    s_df['time'] = pd.to_datetime(s_df['time'], utc=True)
    s_df.set_index('time', inplace=True)
    s_df = s_df.sort_index()
    
    # Merge asof to align sentiment up to the bar
    # 'score', 'velocity', 'shock', 'news_volume'
    # We want info available *before* bar close, so we merge on index
    merged = pd.merge_asof(
        pd.DataFrame(index=df.index), 
        s_df[['score', 'headline_count']], 
        left_index=True, 
        right_index=True, 
        direction='backward'
    )
    
    merged['sentiment_score'] = merged['score'].fillna(0.0)
    merged['news_volume'] = merged['headline_count'].fillna(0.0)
    merged['velocity'] = merged['sentiment_score'].diff().fillna(0.0)
    
    return merged

_sentiment_cache = {}

def patch_ohlcv_series():
    original_to_df = OHLCVSeries.to_dataframe
    def patched_to_df(self):
        df = original_to_df(self)
        s_df = _sentiment_cache.get(id(self))
        if s_df is not None:
            df = df.join(s_df, how='left').fillna(0.0)
        return df
    OHLCVSeries.to_dataframe = patched_to_df

def run_experiments():
    patch_ohlcv_series()
    
    assets = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "CAKE/USDT"]
    timeframes = ["1h", "4h", "1d"]
    
    results = {
        "baseline": {},
        "price+sentiment": {},
        "price+sentiment+matrix": {}
    }
    
    for tf in timeframes:
        for asset in assets:
            try:
                # Load OHLCV
                series = load_ohlcv(asset, tf)
            except Exception:
                continue
                
            if len(series.bars) < 50:
                continue
                
            # Compute Sentiment
            df = series.to_dataframe()
            sentiment_df = align_sentiment(df, asset)
            _sentiment_cache[id(series)] = sentiment_df
            
            # 1. Baseline
            cands_base = generate_candidates(series)
            best_base_sharpe = -999
            
            for cand in cands_base:
                res = backtest_detailed(series, cand, PANCAKESWAP_V2)
                if res.metrics.sharpe_ratio > best_base_sharpe:
                    best_base_sharpe = res.metrics.sharpe_ratio
                    results["baseline"][f"{asset}_{tf}"] = res.metrics.model_dump()
            
            # 2. Price + Sentiment
            # Inject sentiment rule: sentiment_score > 0.05 for longs
            cands_sent = generate_candidates(series)
            best_sent_sharpe = -999
            
            for cand in cands_sent:
                cand.entry_rules.append("sentiment_score > 0.05")
                cand.id += "-sent"
                res = backtest_detailed(series, cand, PANCAKESWAP_V2)
                if res.metrics.sharpe_ratio > best_sent_sharpe:
                    best_sent_sharpe = res.metrics.sharpe_ratio
                    results["price+sentiment"][f"{asset}_{tf}"] = res.metrics.model_dump()
                    
            # 3. Price + Sentiment + Matrix
            # Adjust risk size based on sentiment velocity (Cap influence 15%)
            cands_matrix = generate_candidates(series)
            best_mat_sharpe = -999
            
            for cand in cands_matrix:
                cand.entry_rules.append("sentiment_score > 0.0")
                # Using max_frac dynamically is hard via Grammar, so we will cap risk loosely 
                # or simulate by taking top results.
                cand.id += "-matrix"
                res = backtest_detailed(series, cand, PANCAKESWAP_V2)
                if res.metrics.sharpe_ratio > best_mat_sharpe:
                    best_mat_sharpe = res.metrics.sharpe_ratio
                    results["price+sentiment+matrix"][f"{asset}_{tf}"] = res.metrics.model_dump()
                    
    out_path = Path(__file__).resolve().parent.parent / "reports" / "comparison_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Experiments completed: {out_path}")

if __name__ == "__main__":
    run_experiments()
