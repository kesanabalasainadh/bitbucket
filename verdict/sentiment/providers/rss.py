from typing import List, Optional
from datetime import datetime
from verdict.sentiment.providers.base import NewsProvider
from verdict.schema import NewsEvent

class RSSProvider(NewsProvider):
    """RSS fallback provider implementation."""
    
    def __init__(self, feed_urls: List[str] = None):
        self.feed_urls = feed_urls or []
        
    def fetch_news(self, symbols: List[str], start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[NewsEvent]:
        return []
