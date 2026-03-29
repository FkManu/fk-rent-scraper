from __future__ import annotations

BASE_URL = "https://www.immobiliare.it"
SEARCH_PARAM_BLOCKLIST = {"dtcookie"}
LISTING_PATTERNS = (
    r"https://www\.immobiliare\.it/annunci/\d+/?",
    r"/annunci/\d+/?",
)
LIST_SWITCH_SELECTORS = (
    '[data-cy="switch-to-list"]',
    'button[aria-controls*="results-list"]',
)
PREPARE_WAIT_SELECTORS = (
    'ul[data-cy="search-layout-list"] li',
    'article[data-cy="listing-item"]',
    'a[href*="/annunci/"]',
)
SCROLL_SELECTORS = (
    'ul[data-cy="search-layout-list"]',
    '[data-cy="search-layout-list"]',
    'section[data-cy="results-list"]',
)

__all__ = [
    "BASE_URL",
    "LISTING_PATTERNS",
    "LIST_SWITCH_SELECTORS",
    "PREPARE_WAIT_SELECTORS",
    "SCROLL_SELECTORS",
    "SEARCH_PARAM_BLOCKLIST",
]
