from typing import List, Optional
from datetime import datetime
from verdict.sentiment.providers.base import NewsProvider
from verdict.schema import NewsEvent

class AggregateProvider(NewsProvider):
    """Aggregates news from multiple providers, handles deduplication."""
    
    def __init__(self, providers: List[NewsProvider]):
        self.providers = providers
        
    def fetch_news(self, symbols: List[str], start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[NewsEvent]:
        all_events = []
        for provider in self.providers:
            try:
                events = provider.fetch_news(symbols, start, end)
                all_events.extend(events)
            except Exception as e:
                # Log error, safe degradation
                pass
                
        # Deduplication logic
        seen_urls = set()
        unique_events = []
        for event in sorted(all_events, key=lambda x: x.published_at, reverse=True):
            if event.url not in seen_urls:
                seen_urls.add(event.url)
                unique_events.append(event)
                
        return unique_events
