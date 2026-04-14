from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from state import ExtractedPageContent


ScriptBuilder = Callable[[], str | Awaitable[str]]
JsonConverter = Callable[[ExtractedPageContent], dict | Awaitable[dict]]


@dataclass(slots=True)
class DomainJobDetailExtractionConfig:
    sections: list[str]
    script_builder: ScriptBuilder | None = None


# Add domain-specific overrides here.
# Example:
# DOMAIN_JOB_DETAIL_EXTRACTION_CONFIG["example.com"] = DomainJobDetailExtractionConfig(
#     sections=["header", "body"],
#     script_builder=build_example_script,
# )
DOMAIN_JOB_DETAIL_EXTRACTION_CONFIG: dict[str, DomainJobDetailExtractionConfig] = {}


# Add domain-specific JSON converters here when a site needs custom parsing.
DOMAIN_JOB_DETAIL_JSON_CONVERTERS: dict[str, JsonConverter] = {}


def _normalize_hostname(page_url: str | None) -> str:
    if not page_url:
        return ""
    return urlparse(page_url).netloc.lower().removeprefix("www.")


def get_domain_job_detail_extraction_config(page_url: str | None) -> DomainJobDetailExtractionConfig:
    hostname = _normalize_hostname(page_url)
    for domain, config in DOMAIN_JOB_DETAIL_EXTRACTION_CONFIG.items():
        normalized_domain = domain.lower().removeprefix("www.")
        if hostname == normalized_domain or hostname.endswith(f".{normalized_domain}"):
            return config
    return DomainJobDetailExtractionConfig(sections=["header", "body"])


def get_domain_job_detail_json_converter(page_url: str | None) -> JsonConverter | None:
    hostname = _normalize_hostname(page_url)
    for domain, converter in DOMAIN_JOB_DETAIL_JSON_CONVERTERS.items():
        normalized_domain = domain.lower().removeprefix("www.")
        if hostname == normalized_domain or hostname.endswith(f".{normalized_domain}"):
            return converter
    return None
