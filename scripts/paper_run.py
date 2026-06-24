import json
from datetime import datetime, timezone
from pathlib import Path
from verdict.schema import Decision, Verdict

def run_paper_replay():
    # Simulate a paper run over a subset of historical bars
    # "for each bar: load historical news -> score sentiment -> run matrix -> emit verdict -> record result"
    
    results = []
    # Dummy data representing the paper simulation
    for i in range(10):
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        
        results.append({
            "ts": ts.isoformat(),
            "symbol": "BTC/USDT",
            "news_events": 2,
            "sentiment_score": 0.45,
            "verdict": Verdict.NO_TRADE.value,
            "reason": "Sentiment passed but price momentum failed matrix check"
        })
        
    out_path = Path(__file__).resolve().parent.parent / "reports" / "paper_run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Paper run saved to {out_path}")

if __name__ == "__main__":
    run_paper_replay()
