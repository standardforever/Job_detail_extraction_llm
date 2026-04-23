from __future__ import annotations

from urllib.parse import urljoin, urlparse


WEB_NAVIGATION_SCHEMES = {"", "http", "https"}


def normalize_navigation_url(target_url: str | None, base_url: str | None) -> str | None:
    normalized_target = str(target_url or "").strip()
    if not normalized_target:
        return None
    normalized_base = str(base_url or "").strip()
    if not normalized_base:
        return normalized_target
    return urljoin(normalized_base, normalized_target)


def is_web_navigation_url(url: str | None) -> bool:
    normalized = str(url or "").strip()
    if not normalized:
        return False
    return urlparse(normalized).scheme.lower() in WEB_NAVIGATION_SCHEMES


def is_email_navigation_url(url: str | None) -> bool:
    return str(url or "").strip().lower().startswith("mailto:")


def detect_external_job_board(url: str | None) -> str | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None
    domain = urlparse(normalized).netloc.lower()
    if "linkedin." in domain:
        return "linkedin"
    if "indeed." in domain:
        return "indeed"
    return None
