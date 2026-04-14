from __future__ import annotations

from urllib.parse import parse_qs, urlparse


DOCUMENT_EXTENSIONS = {
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".rtf": "rtf",
    ".odt": "odt",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".ppt": "ppt",
    ".pptx": "pptx",
    ".zip": "zip",
}


def classify_url_target(url: str | None) -> dict[str, str | bool | None]:
    if not url:
        return {"is_webpage": False, "kind": "unknown", "reason": "Missing URL"}

    parsed = urlparse(url)
    lower_path = parsed.path.lower()

    for extension, kind in DOCUMENT_EXTENSIONS.items():
        if lower_path.endswith(extension):
            return {
                "is_webpage": False,
                "kind": kind,
                "reason": f"URL path ends with {extension}",
            }

    query = parse_qs(parsed.query)
    file_type = (query.get("type") or [None])[0]
    if file_type:
        normalized_type = str(file_type).lower()
        if normalized_type in {"pdf", "doc", "docx", "rtf", "odt", "xls", "xlsx", "csv", "ppt", "pptx", "zip"}:
            return {
                "is_webpage": False,
                "kind": normalized_type,
                "reason": f"URL query indicates downloadable {normalized_type} file",
            }

    if "download" in lower_path or "attachment" in lower_path:
        return {
            "is_webpage": False,
            "kind": "download",
            "reason": "URL path suggests a downloadable attachment",
        }

    return {
        "is_webpage": True,
        "kind": "webpage",
        "reason": "URL looks like a normal webpage",
    }
