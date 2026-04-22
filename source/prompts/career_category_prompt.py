def create_job_page_analysis_prompt(url: str | None, text: str, interactive_links: str | None = None) -> str:
    return f"""Analyze the webpage and classify its job-related status. Never hallucinate — only use what is explicitly in the page text.

URL: {url}

PAGE CONTENT:
{text}

VISIBLE INTERACTIVE LINKS/BUTTONS:
{interactive_links or "None"}

---

## PAGE CATEGORIES (choose ONE)

| Category | When to use |
|---|---|
| `jobs_listed` | Multiple job postings visible on this page |
| `job_listings_preview_page` | Subset of jobs shown + link to view ALL jobs elsewhere |
| `navigation_required` | No jobs visible but page points to where jobs are |
| `single_job_posting` | One specific job described (detailed or minimal) |
| `not_job_related` | No job/career/hiring content at all |

---

## KEY RULES

**URLs:** If page_category is `single_job_posting` → job_url = {url}

RULE — Resolving job_url from extracted links:
BASE URL: {url}
- Case 1 — Link starts with "/":
  Take the Base URL above, remove everything after the domain name, then attach the link.
  The domain name includes any subdomain — do not remove it.

  BASE: https://www.site.com/community/jobs   +  /role-x  →  https://www.site.com/role-x
  BASE: https://jobs.site.com/board           +  /role-x  →  https://jobs.site.com/role-x

- Case 2 — Link starts with "http://" or "https://":
  Use it exactly as found. Do not change anything.
- Do not guess, infer, or modify URLs beyond these two cases.


**Job alert:** Set `job_alert = true` only if page explicitly mentions signing up for vacancy/job alert notifications.

**Navigation vs job links:** Links next to job titles (Apply, View Details, More Info) are `job_url`, not navigation targets.

**Preview page:** If SOME jobs are shown AND a "view all" link exists → `job_listings_preview_page`, populate `next_action_target`.

**Selector map links:** The `VISIBLE INTERACTIVE LINKS/BUTTONS` section is extracted from the DOM selector map. If page text mentions a navigation link/button but the URL is missing from the markdown, use the matching URL from this section.

---

## JOBS LISTED ON PAGE (when page_category = `jobs_listed`)

For each job extract:
- `title` — job title
- `job_url` — full resolved URL or null

Then classify the page-level listing UI and pagination:

**ui_category** — how jobs are presented:
| Value | Meaning |
|---|---|
| `linked_cards` | Each job links to its own detail page |
| `embedded_only` | Full details inline, NO separate detail page — job_url MUST be null |
| `modal_popup` | Clicking opens an overlay on the same page |
| `expandable_accordion` | Jobs expand in-place on click |
| `apply_inline` | Apply form embedded directly on listing page |
| `external_redirect` | Job links point directly to an external/ATS domain |

**pagination_type** — if pagination controls are visible:
| Value | Meaning |
|---|---|
| `numbered` | Numbered page links (1, 2, 3…) |
| `next_prev` | Next / Previous buttons only |
| `load_more` | Single "Load More" or "Show More" button |
| `infinite_scroll` | Auto-loading / infinite scroll referenced |
| `cursor_based` | URL uses cursor, token, or offset param |
| `alphabet` | A–Z letter navigation |

---

## PAGE ACCESS STATUS

| Value | When |
|---|---|
| `accessible` | Loaded normally |
| `bot_detected` | CAPTCHA, Cloudflare challenge, access denied |
| `login_required` | Auth required to view content |
| `not_found` | 404 or page not found |
| `empty_or_blank` | Loaded but no meaningful content |
| `error` | 500 / 503 / maintenance page |

If NOT accessible, still attempt classification at lower confidence.

---

## RESPONSE SCHEMA

Return ONLY valid JSON. No markdown, no extra text. Start with {{ end with }}.

{{
    "page_category": "jobs_listed" | "job_listings_preview_page" | "navigation_required" | "single_job_posting" | "not_job_related",
    "confidence": <float 0.0–1.0>,
    "reasoning": "<concise explanation>",
    "job_alert": boolean | null,
    "page_access_status": "accessible" | "bot_detected" | "login_required" | "not_found" | "empty_or_blank" | "error",
    "page_access_issue_detail": "<short description or null>",
    "next_action_target": {{
        "url": "<URL or null>",
        "button": "<text or null>",
        "element_type": "link" | "button" | null
    }},
    "jobs_listed_on_page": [
        {{
            "title": "<job title>",
            "job_url": "<full resolved URL or null>"
        }}
    ],
    "listing_ui": {{
        "ui_category": "linked_cards" | "embedded_only" | "modal_popup" | "expandable_accordion" | "apply_inline" | "external_redirect" | null,
        "filter_present": boolean,
        "filter_types": ["<filter label>"],
        "sort_present": boolean,
        "sort_types": ["<sort label>"],
        "pagination_present": boolean,
        "pagination_type": "numbered" | "next_prev" | "load_more" | "infinite_scroll" | "cursor_based" | "alphabet" | null,
        "next_page_url": "<URL or null>"
    }}
}}

Note: `listing_ui` fields should be null/empty when page_category is not `jobs_listed`.
"""
