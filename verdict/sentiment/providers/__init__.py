from verdict.sentiment.providers.base import NewsProvider
from verdict.sentiment.providers.cryptopanic import CryptoPanicProvider
from verdict.sentiment.providers.newsdata import NewsDataProvider
from verdict.sentiment.providers.rss import RSSProvider
from verdict.sentiment.providers.aggregate import AggregateProvider

__all__ = [
    "NewsProvider",
    "CryptoPanicProvider",
    "NewsDataProvider",
    "RSSProvider",
    "AggregateProvider"
]
