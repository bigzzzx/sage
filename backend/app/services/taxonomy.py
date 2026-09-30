"""分层 Taxonomy 加载服务（v2）。

数据结构（三层）：
    Track（big_data / database / network…）
      └── Service（glue / emr / athena…）
            └── Capability（旧称 dimension / sub_skill）
                  └── Levels: L1 / L2 / L3
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
TAXONOMY_DIR = DATA_DIR / "taxonomy"
TRACKS_PATH = TAXONOMY_DIR / "tracks.json"
SERVICES_DIR = TAXONOMY_DIR / "services"


@lru_cache(maxsize=1)
def get_tracks() -> dict[str, Any]:
    """加载 Track 列表。"""
    with open(TRACKS_PATH, encoding="utf-8") as fp:
        return json.load(fp)


@lru_cache(maxsize=32)
def get_service(service_id: str) -> dict[str, Any] | None:
    """加载单个 Service 的完整定义（含 capabilities）。"""
    path = SERVICES_DIR / f"{service_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def list_services() -> list[dict[str, Any]]:
    """列出所有 Service 简要信息（从 tracks.json 拼出来）。"""
    tracks = get_tracks().get("tracks", [])
    out = []
    for t in tracks:
        for s in t.get("services", []):
            out.append({**s, "track_id": t["id"], "track_name": t["name"]})
    return out


def get_profile_services(profile_id: str) -> list[dict[str, Any]]:
    """Return service summaries for one profile/track."""
    track = next((item for item in get_tracks().get("tracks", [])
                  if item.get("id") == profile_id), None)
    if not track:
        return []
    return [{**service, "track_id": track["id"], "track_name": track["name"]}
            for service in track.get("services", [])]


def get_full_taxonomy() -> dict[str, Any]:
    """返回完整 taxonomy（Track + 每个 Service 的简要 + Capability 详情）。

    给前端"测评配置页"和"经理看板"使用。
    """
    tracks_data = get_tracks()
    full = {"version": tracks_data.get("version", "2.0"), "tracks": []}
    for t in tracks_data.get("tracks", []):
        track_out = {
            "id": t["id"],
            "name": t["name"],
            "icon": t.get("icon", ""),
            "description": t.get("description", ""),
            "services": [],
        }
        for s in t.get("services", []):
            svc_full = get_service(s["id"])
            track_out["services"].append({
                "id": s["id"],
                "name": s["name"],
                "icon": s.get("icon", ""),
                "is_real": s.get("is_real", False),
                "summary": s.get("summary", ""),
                "capabilities": (svc_full or {}).get("capabilities", []),
            })
        full["tracks"].append(track_out)
    return full
