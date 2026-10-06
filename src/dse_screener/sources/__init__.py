"""Data source adapters. Each site gets its own module returning normalized data."""

from .base import PRICE_COLUMNS, PriceSource
from .dse_archive import DseArchiveSource
from .dse_company import DseCompanySource
from .dse_market import DseMarketStatsSource, DseMarketSummarySource
from .dse_news import DseNewsSource

__all__ = ["PRICE_COLUMNS", "PriceSource", "DseArchiveSource", "DseCompanySource", "DseMarketStatsSource", "DseMarketSummarySource", "DseNewsSource"]
