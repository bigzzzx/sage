"""Capture reachable AWS documentation excerpts in the local D-drive cache.

Only URLs already referenced by the service taxonomy are considered. Failed
fetches are reported and left as metadata-only references in the RAG corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.services.rag import OFFICIAL_DOC_CACHE_DIR, OFFICIAL_HOSTS
from app.services.glue_sources import load_glue_facts
from app.services.taxonomy import get_full_taxonomy
from app.services.ticket_quality import preferred_official_source


def referenced_urls(service_id: str | None = None) -> list[str]:
    refs = set()
    for track in get_full_taxonomy().get("tracks", []):
        for service in track.get("services", []):
            if service_id and service["id"] != service_id:
                continue
            for capability in service.get("capabilities", []):
                for ref in capability.get("doc_refs") or []:
                    url = ref.get("url", "")
                    parsed = urlparse(url)
                    if (parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
                            and parsed.port in {None, 443} and not parsed.username
                            and not parsed.password):
                        refs.add(url)
    if service_id in {None, "glue"}:
        refs.update(fact["source"] for fact in load_glue_facts()
                    if urlparse(fact["source"]).hostname in OFFICIAL_HOSTS)
    return sorted(refs)


def capture(url: str, refresh: bool = False) -> dict:
    target = OFFICIAL_DOC_CACHE_DIR / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")
    if target.exists() and not refresh:
        return {"url": url, "status": "cached"}
    resolved_url, excerpt = preferred_official_source(url)
    resolved = urlparse(resolved_url)
    if (len(excerpt.strip()) < 100 or resolved.scheme != "https"
            or resolved.hostname not in OFFICIAL_HOSTS or resolved.port not in {None, 443}
            or resolved.username or resolved.password):
        return {"url": url, "status": "unavailable"}
    excerpt = excerpt.strip()
    snapshot = {
        "source_url": url,
        "resolved_url": resolved_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "text": excerpt,
        "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return {"url": url, "resolved_url": resolved_url, "status": "captured",
            "characters": len(excerpt)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", help="Restrict to one taxonomy service")
    parser.add_argument("--limit", type=int, help="Limit URLs for a small initial run")
    parser.add_argument("--refresh", action="store_true", help="Replace existing snapshots")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be 1..8")
    urls = referenced_urls(args.service)
    if args.limit:
        urls = urls[:args.limit]
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(capture, url, args.refresh): url for url in urls}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:  # keep one failure from hiding other documents
                result = {"url": futures[future], "status": "error",
                          "error": f"{type(exc).__name__}: {exc}"}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    counts = {status: sum(item["status"] == status for item in results)
              for status in ("captured", "cached", "unavailable", "error")}
    print(json.dumps({"requested": len(urls), **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
