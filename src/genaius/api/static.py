"""Allowlisted static frontend assets (no directory listing, no traversal)."""
from __future__ import annotations

from pathlib import Path

FRONTEND_TOP_ALLOWLIST = {
    "/": "index.html",
    "/index.html": "index.html",
    "/fire.html": "fire.html",
    "/material-lab.html": "material-lab.html",
    "/data.html": "data.html",
    "/case-saffire.html": "case-saffire.html",
    "/favicon.png": "favicon.png",
}
FRONTEND_ALLOWED_DIRS = frozenset({"assets", "css", "js"})
MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def resolve_frontend_asset(frontend_root: Path | None, url_path: str) -> tuple[Path, str] | None:
    """Resolve an allowlisted static asset strictly within frontend_root."""
    if frontend_root is None or "\\" in url_path or "\x00" in url_path:
        return None
    if url_path in FRONTEND_TOP_ALLOWLIST:
        rel_parts: tuple[str, ...] = (FRONTEND_TOP_ALLOWLIST[url_path],)
    else:
        raw_parts = url_path.lstrip("/").split("/")
        if len(raw_parts) != 2 or raw_parts[0] not in FRONTEND_ALLOWED_DIRS:
            return None
        if not raw_parts[1] or raw_parts[1].startswith(".") or ".." in raw_parts:
            return None
        rel_parts = tuple(raw_parts)

    mime = MIME_TYPES.get(Path(rel_parts[-1]).suffix.lower())
    if mime is None:
        return None
    base_resolved = frontend_root.resolve()
    candidate = frontend_root.joinpath(*rel_parts).resolve()
    if not candidate.is_relative_to(base_resolved) or not candidate.is_file():
        return None
    return candidate, mime


def resolve_ai_use_doc(repo_root: Path) -> Path | None:
    docs_root = (repo_root / "docs").resolve()
    ai_doc = (docs_root / "AI_USE.md").resolve()
    return ai_doc if ai_doc.is_relative_to(docs_root) and ai_doc.is_file() else None
