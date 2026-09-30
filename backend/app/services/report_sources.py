"""Prefer reachable Chinese AWS documentation when presenting a saved report."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from urllib.parse import urlparse

from app.services.ticket_quality import preferred_official_source

OFFICIAL_HOSTS = {"docs.aws.amazon.com", "docs.amazonaws.cn"}


def localize_report_sources(questions: list[dict], plan: dict | None,
                            gaps: list[dict], sources: list[dict]) -> tuple[list[dict], dict | None, list[dict], list[dict]]:
    """Keep original URLs if no localized page can actually be fetched."""
    questions, plan, gaps, sources = (deepcopy(questions), deepcopy(plan),
                                     deepcopy(gaps), deepcopy(sources))
    urls: set[str] = set()
    plan_urls: set[str] = set()
    for question in questions:
        urls.update(ref.get("url", "") for ref in question.get("source_refs", []) if isinstance(ref, dict))
    for week in (plan or {}).get("weekly_plan", []):
        for task in week.get("tasks", []):
            plan_urls.update(item.get("url", "") for item in task.get("concepts", []) if isinstance(item, dict))
            plan_urls.update(item.get("url", "") for item in task.get("resources", []) if isinstance(item, dict))
            plan_urls.add(task.get("hands_on_url", ""))
    urls.update(plan_urls)
    for gap in gaps:
        urls.update(gap.get("suggested_doc_urls") or [])
    urls.update(source.get("url", "") for source in sources)
    def official(url: str) -> bool:
        return (isinstance(url, str) and urlparse(url).scheme == "https" and
                urlparse(url).hostname in OFFICIAL_HOSTS)

    # A plan can contain more links than the old 24-URL cap. Resolve its links first
    # so an older English study plan never loses its Chinese candidates to question refs.
    targets = ([url for url in sorted(plan_urls) if official(url)] +
               [url for url in sorted(urls - plan_urls) if official(url)])[:48]
    def resolve(url: str) -> str:
        try:
            return preferred_official_source(url)[0] or url
        except Exception:  # A documentation outage must not hide the report.
            return url

    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = dict(zip(targets, pool.map(resolve, targets)))
    for question in questions:
        for ref in question.get("source_refs", []):
            if isinstance(ref, dict):
                ref["url"] = resolved.get(ref.get("url", ""), ref.get("url", ""))
    for week in (plan or {}).get("weekly_plan", []):
        for task in week.get("tasks", []):
            for item in task.get("concepts", []):
                if isinstance(item, dict):
                    item["url"] = resolved.get(item.get("url", ""), item.get("url", ""))
            for item in task.get("resources", []):
                if isinstance(item, dict):
                    item["url"] = resolved.get(item.get("url", ""), item.get("url", ""))
            task["hands_on_url"] = resolved.get(task.get("hands_on_url", ""), task.get("hands_on_url", ""))
    for gap in gaps:
        gap["suggested_doc_urls"] = [resolved.get(url, url) for url in (gap.get("suggested_doc_urls") or [])]
    for source in sources:
        source["url"] = resolved.get(source.get("url", ""), source.get("url", ""))
    return questions, plan, gaps, sources
