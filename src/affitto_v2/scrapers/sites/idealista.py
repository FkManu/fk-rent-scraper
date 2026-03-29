from __future__ import annotations

import re

BASE_URL = "https://www.idealista.it"
SEARCH_PARAM_BLOCKLIST = {"dtcookie", "xtor", "xts"}
LISTING_PATTERNS = (
    r"https://www\.idealista\.it/immobile/\d+/?",
    r"/immobile/\d+/?",
)
AGENCY_ATTR_SELECTORS = (
    'figure[class*="listingCardAgencyLogo"] img',
    'img[class*="listingCardAgencyLogo"]',
    'a[href*="/pro/"] img[alt]',
    'img[alt*="Agenzia"]',
    'img[alt*="Immobiliare"]',
)
AGENCY_TEXT_SELECTORS = (
    '[class*="advertiser"] [class*="name"]',
    '[data-testid="company-name"]',
    '.item-info [class*="item-brand"]',
    '.item-info [class*="company"]',
    'a[href*="/agenzie-immobiliari/"]',
    'a[href*="/pro/"]',
)
PRIVATE_ONLY_MAX_CHECKS = 15
PRIVATE_ONLY_DELAY_MS = (900, 1800)
PRIVATE_ONLY_BATCH_PAUSE_EVERY = 4
PRIVATE_ONLY_BATCH_PAUSE_MS = (1600, 3200)
PREPARE_WAIT_SELECTORS = (
    'a[itemprop="url"]',
    'a[href*="/immobile/"]',
    "article",
)
DETAIL_PRO_LINK_SELECTOR = 'aside a[href*="/pro/"], [role="complementary"] a[href*="/pro/"], nav a[href*="/pro/"]'


def _normalize(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def classify_publisher_kind(body_text: str) -> str:
    haystack = _normalize(body_text).lower()
    if not haystack:
        return ""

    anchors = (
        "persona che pubblica l'annuncio",
        "annuncio pubblicato da",
        "contatta l'inserzionista",
    )
    for anchor in anchors:
        idx = haystack.find(anchor)
        if idx < 0:
            continue
        window = haystack[idx : idx + 240]
        if re.search(r"\bprofessionista\b", window):
            return "professionista"
        if re.search(r"\bprivato\b", window):
            return "privato"

    professional_hits = len(re.findall(r"\bprofessionista\b", haystack))
    private_hits = len(re.findall(r"\bprivato\b", haystack))
    if professional_hits >= 2 and private_hits == 0:
        return "professionista"
    if private_hits >= 2 and professional_hits == 0:
        return "privato"
    return ""


def classify_publisher_kind_from_signals(*, body_text: str, has_professional_profile_link: bool) -> str:
    if has_professional_profile_link:
        return "professionista"
    return classify_publisher_kind(body_text)


__all__ = [
    "AGENCY_ATTR_SELECTORS",
    "AGENCY_TEXT_SELECTORS",
    "BASE_URL",
    "DETAIL_PRO_LINK_SELECTOR",
    "LISTING_PATTERNS",
    "PREPARE_WAIT_SELECTORS",
    "PRIVATE_ONLY_BATCH_PAUSE_EVERY",
    "PRIVATE_ONLY_BATCH_PAUSE_MS",
    "PRIVATE_ONLY_DELAY_MS",
    "PRIVATE_ONLY_MAX_CHECKS",
    "SEARCH_PARAM_BLOCKLIST",
    "classify_publisher_kind",
    "classify_publisher_kind_from_signals",
]
