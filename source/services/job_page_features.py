from __future__ import annotations

import re
from typing import Any

try:
    from playwright.async_api import Page
except Exception:  # pragma: no cover - handled gracefully at runtime
    Page = None

from state import ExtractedPageContent, JobPageFeatures


async def _detect_job_detail_targets(page: Page | None) -> dict[str, Any]:
    if page is None:
        return {"count": 0, "types": []}

    result = await page.evaluate(
        """
        () => {
          const root = document.querySelector('main, article, [role="main"]') || document.body;
          const candidates = Array.from(
            root.querySelectorAll(
              'a[href], button, [role="button"], [data-url], [data-href], [data-link], [data-permalink], [data-job-url], [data-ep-wrapper-link], [onclick]'
            )
          );
          const seen = new Set();
          const matches = [];

          const excludedPattern = /^(apply|apply now|easy apply|submit application|sign in|log in|share|save|bookmark)$/i;
          const detailPattern = /(view|details|detail|description|read more|see more|learn more|job|role|position)/i;
          const cardPattern = /(job|role|position|posting|opening|vacan|career|opportunit)/i;

          function getLabel(el) {
            return (
              el.textContent ||
              el.getAttribute('aria-label') ||
              el.getAttribute('title') ||
              ''
            ).replace(/\\s+/g, ' ').trim();
          }

          function getActionUrl(el) {
            const directUrl = (
              el.getAttribute('href') ||
              el.getAttribute('data-url') ||
              el.getAttribute('data-href') ||
              el.getAttribute('data-link') ||
              el.getAttribute('data-permalink') ||
              el.getAttribute('data-job-url') ||
              ''
            ).trim();
            if (directUrl) {
              return directUrl;
            }

            const wrapperLink = (el.getAttribute('data-ep-wrapper-link') || '').trim();
            if (!wrapperLink) {
              return '';
            }

            try {
              return (JSON.parse(wrapperLink).url || '').trim();
            } catch (_error) {
              try {
                return (JSON.parse(wrapperLink.replace(/&quot;/g, '"')).url || '').trim();
              } catch (_nestedError) {
                return '';
              }
            }
          }

          function getCard(el) {
            return el.closest(
              '[data-job-id], [data-post-id], article, li, tr, .job, .jobs, .job-card, .job-item, .posting, .opening, .position'
            );
          }

          for (const el of candidates) {
            const label = getLabel(el);
            const normalized = label.toLowerCase();
            if (!label || excludedPattern.test(normalized)) {
              continue;
            }

            const url = getActionUrl(el);
            const card = getCard(el);
            const cardText = ((card && card.textContent) || '').replace(/\\s+/g, ' ').trim();
            const inJobCard = cardPattern.test(cardText) || cardPattern.test(el.className || '') || cardPattern.test(el.id || '');
            const titleLike = label.length >= 4 && label.length <= 140 && /^[A-Za-z0-9]/.test(label);
            const looksLikeDetailTarget = detailPattern.test(label) || (titleLike && inJobCard);

            if (!looksLikeDetailTarget) {
              continue;
            }

            const type =
              el.tagName.toLowerCase() === 'a'
                ? (detailPattern.test(label) ? 'detail_link' : 'job_title_link')
                : 'detail_button';
            const key = `${type}:${label}:${url}`;
            if (seen.has(key)) {
              continue;
            }

            seen.add(key);
            matches.push({ type, label, url });
          }

          return {
            count: matches.length,
            types: Array.from(new Set(matches.map((item) => item.type))),
          };
        }
        """
    )
    if not isinstance(result, dict):
        return {"count": 0, "types": []}

    return {
        "count": int(result.get("count", 0) or 0),
        "types": [str(item) for item in result.get("types", []) if item],
    }


async def detect_job_page_features(
    extracted_content: ExtractedPageContent | None,
    page: Page | None,
) -> JobPageFeatures:
    markdown = (extracted_content or {}).get("markdown", "")
    selector_map = ((extracted_content or {}).get("metadata") or {}).get("selector_map", {})
    selector_labels = [
        " ".join(
            str(value)
            for value in (
                selector_data.get("label"),
                selector_data.get("tag"),
                selector_data.get("kind"),
                selector_data.get("action_url"),
                (selector_data.get("attributes") or {}).get("aria-label"),
                (selector_data.get("attributes") or {}).get("title"),
                (selector_data.get("attributes") or {}).get("href"),
                (selector_data.get("attributes") or {}).get("data-href"),
                (selector_data.get("attributes") or {}).get("data-url"),
                (selector_data.get("attributes") or {}).get("data-link"),
                (selector_data.get("attributes") or {}).get("data-ep-wrapper-link"),
            )
            if value
        )
        for selector_data in selector_map.values()
        if isinstance(selector_data, dict)
    ]
    haystack = f"{markdown}\n{' '.join(selector_labels)}".lower()

    filter_keywords = [
        "filter",
        "location",
        "country",
        "department",
        "category",
        "team",
        "employment type",
        "job type",
        "work type",
        "remote",
        "hybrid",
        "onsite",
    ]
    sort_keywords = [
        "sort",
        "most recent",
        "newest",
        "latest",
        "date posted",
        "relevance",
    ]
    pagination_keywords = [
        "next",
        "previous",
        "page 2",
        "load more",
        "show more",
        "older jobs",
        "newer jobs",
    ]

    detected_filter_types = [keyword for keyword in filter_keywords if keyword in haystack]
    detected_sort_types = [keyword for keyword in sort_keywords if keyword in haystack]
    detected_pagination_signals = [keyword for keyword in pagination_keywords if keyword in haystack]
    if re.search(r"\bpage\s+\d+\b", haystack):
        detected_pagination_signals.append("numbered_pages")

    pagination_type = None
    if "load more" in detected_pagination_signals or "show more" in detected_pagination_signals:
        pagination_type = "load_more"
    elif "numbered_pages" in detected_pagination_signals:
        pagination_type = "numbered"
    elif detected_pagination_signals:
        pagination_type = "next_previous"

    detail_target_info = await _detect_job_detail_targets(page)

    return {
        "filter_present": bool(detected_filter_types),
        "filter_types": sorted(set(detected_filter_types)),
        "pagination_present": bool(detected_pagination_signals),
        "pagination_type": pagination_type,
        "sort_present": bool(detected_sort_types),
        "sort_types": sorted(set(detected_sort_types)),
        "job_detail_target_present": detail_target_info["count"] > 0,
        "job_detail_target_types": sorted(set(detail_target_info["types"])),
        "job_detail_target_count": detail_target_info["count"],
    }
