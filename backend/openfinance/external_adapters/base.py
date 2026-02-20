from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExternalNewsItem:
    item_id: str
    headline: str
    source: str
    timestamp: datetime
    url: str
    summary: str


@dataclass(frozen=True)
class ExternalMacroItem:
    item_id: str
    headline: str
    source: str
    timestamp: datetime
    url: str
    summary: str


@dataclass(frozen=True)
class ExternalFilingItem:
    item_id: str
    headline: str
    source: str
    timestamp: datetime
    url: str
    summary: str


class NewsProviderBase(ABC):
    provider_name: str = "news-base"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[ExternalNewsItem]:
        raise NotImplementedError


class MacroProviderBase(ABC):
    provider_name: str = "macro-base"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[ExternalMacroItem]:
        raise NotImplementedError


class FilingsProviderBase(ABC):
    provider_name: str = "filings-base"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[ExternalFilingItem]:
        raise NotImplementedError

