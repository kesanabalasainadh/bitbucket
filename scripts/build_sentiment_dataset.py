import csv
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from verdict.schema import NewsEvent

def build_dataset(output_path: Path):
    symbols = ["BNB/USDT", "CAKE/USDT", "BTC/USDT", "ETH/USDT"]
    start_date = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    # 4h intervals
    interval = timedelta(hours=4)
    
    # deterministic seed for reproducibility
    random.seed(42)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["asset", "time", "headline_count", "positive", "negative", "neutral", "score", "confidence"])
        
        for symbol in symbols:
            curr = start_date
            while curr <= end_date:
                # generate fake but deterministic sentiment to simulate a "dataset"
                headline_count = random.randint(0, 10)
                if headline_count > 0:
                    positive = random.randint(0, headline_count)
                    negative = random.randint(0, headline_count - positive)
                    neutral = headline_count - positive - negative
                    score = (positive - negative) / headline_count
                    confidence = random.uniform(0.5, 1.0)
                else:
                    positive = negative = neutral = 0
                    score = 0.0
                    confidence = 0.0
                
                writer.writerow([
                    symbol,
                    curr.isoformat(),
                    headline_count,
                    positive,
                    negative,
                    neutral,
                    round(score, 4),
                    round(confidence, 4)
                ])
                curr += interval

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data" / "sentiment_snapshot.csv"
    build_dataset(out)
    print(f"Dataset built at {out}")
