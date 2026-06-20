from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from verdict.schema import NewsEvent

class NewsProvider(ABC):
    """Abstract base class for news ingestion providers."""
    
    @abstractmethod
    def fetch_news(self, symbols: List[str], start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[NewsEvent]:
        """Fetch news for given symbols within a time window."""
        pass
