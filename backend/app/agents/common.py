"""Agent 共用工具：JSON 解析 + 文档池构造 + Learning Path 加载。"""
from __future__ import annotations

import json
from pathlib import Path


def strip_code_fence(text: str) -> str:
    """LLM 偶尔会用 ``` 包裹 JSON，剥掉。"""
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s


def safe_json_loads(text: str, fallback: object) -> object:
    """安全解析 LLM JSON 输出，失败返回 fallback。"""
    try:
        return json.loads(strip_code_fence(text))
    except (json.JSONDecodeError, TypeError):
        return fallback


def build_doc_pool(svc: dict) -> tuple[str, set[str], dict[str, list[dict]]]:
    """根据 service 的 capabilities[].doc_refs 构建给 LLM 看的资料库。

    返回：
      - prompt_text：可直接拼进 prompt 的 markdown 文本
      - allowed_urls：合法 URL 集合（用于白名单兜底）
      - by_capability：{capability_id: [doc_ref, ...]}，给诊断 agent 按需查
    """
    lines: list[str] = []
    allowed: set[str] = set()
    by_cap: dict[str, list[dict]] = {}

    caps = svc.get("capabilities", []) if svc else []
    for cap in caps:
        cap_id = cap.get("id", "")
        refs = cap.get("doc_refs") or []
        if not refs:
            by_cap[cap_id] = []
            continue
        by_cap[cap_id] = refs
        lines.append(f"## [{cap_id}] {cap.get('name', cap_id)}")
        for r in refs:
            url = (r.get("url") or "").strip()
            if not url:
                continue
            allowed.add(url)
            title = r.get("title", "")
            summary = r.get("summary", "")
            lines.append(f"- [{title}]({url})  —  {summary}")
        lines.append("")
    pool_text = "\n".join(lines).strip() or "（暂无文档资料库）"
    return pool_text, allowed, by_cap


def filter_doc_pool_to_capabilities(svc: dict, capability_ids: list[str]) -> tuple[str, set[str]]:
    """只展示指定 capability 的文档池，给规划 agent 减少 prompt 冗余。"""
    if not capability_ids:
        text, allowed, _ = build_doc_pool(svc)
        return text, allowed

    keep_ids = set(capability_ids)
    sub_svc = {
        **svc,
        "capabilities": [c for c in svc.get("capabilities", []) if c.get("id") in keep_ids],
    }
    text, allowed, _ = build_doc_pool(sub_svc)
    return text, allowed


def enforce_url_whitelist(items: list[dict], allowed_urls: set[str], url_field: str = "url") -> None:
    """通用：把列表元素的 url 字段限制在白名单里，未命中的清空。"""
    for it in items:
        url = (it.get(url_field) or "").strip()
        if url and url not in allowed_urls:
            it[url_field] = ""


# ---------- Learning Path 加载 ----------

LEARNING_PATH_DIR = Path(__file__).resolve().parents[3] / "data" / "taxonomy" / "learning_path"


def load_learning_path(service_id: str) -> str:
    """加载该 service 的 Learning Path，格式化为 prompt 文本。"""
    path = LEARNING_PATH_DIR / f"{service_id}.json"
    if not path.exists():
        return ""
    import json
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    lines: list[str] = []
    for module in data.get("modules", []):
        lines.append(f"## {module['name']}")
        for level in ("basic", "intermediate", "advanced"):
            info = module.get(level) or {}
            if not info:
                continue
            level_label = {"basic": "Basic (L1)", "intermediate": "Intermediate (L2)", "advanced": "Advanced (L3)"}[level]
            topics = info.get("topics", [])
            resources = info.get("resources", [])
            labs = info.get("labs", [])
            lines.append(f"### {level_label}")
            if topics:
                lines.append("学习内容：" + " / ".join(topics))
            if resources:
                lines.append("学习资料：" + " / ".join(resources))
            if labs:
                lines.append("练习场景：" + " / ".join(labs))
        lines.append("")
    return "\n".join(lines).strip()
