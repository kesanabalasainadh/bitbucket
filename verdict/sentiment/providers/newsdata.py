from typing import List, Optional
from datetime import datetime
from verdict.sentiment.providers.base import NewsProvider
from verdict.schema import NewsEvent

class NewsDataProvider(NewsProvider):
    """NewsData.io provider implementation."""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        
    def fetch_news(self, symbols: List[str], start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[NewsEvent]:
        return []
