"""Manager-reviewed knowledge contributions and owner-scoped case submissions."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.db import SessionLocal
from app.models import AdminAudit, KnowledgeEntry, TicketSession, User
from app.services.profile_scope import record_profile_id, service_in_profile, service_profile_id
from app.services.rag import (KnowledgeDocument, OFFICIAL_HOSTS, _chunk_document,
                              get_retriever, knowledge_coverage, load_knowledge_documents)
from app.services.taxonomy import get_service
from app.services.ticket_quality import preferred_official_source

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
_FIELDS = ("symptom", "investigation", "root_cause", "resolution", "verification")
_LABELS = ("客户现象", "排查过程", "问题根因", "解决方案", "验证方式")
_SENSITIVE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b\d{12}\b|"
                        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


class KnowledgeInput(BaseModel):
    profile_id: str = Field(max_length=32)
    service_id: str = Field(max_length=32)
    capability_id: str = Field(default="", max_length=64)
    source_type: Literal["case", "official_doc"]
    title: str = Field(min_length=4, max_length=160)
    url: str = Field(default="", max_length=1024)
    details: dict[str, str] = Field(default_factory=dict)
    source_ticket_id: str | None = Field(default=None, max_length=32)
    replaces_entry_id: str | None = Field(default=None, max_length=32)


def _manager(current: dict) -> None:
    if current.get("r") != "manager":
        raise HTTPException(403, "仅管理员可管理知识库")


def _official_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
                and parsed.port in {None, 443} and not parsed.username
                and not parsed.password and not parsed.fragment)
    except ValueError:
        return False


def _validate_input(req: KnowledgeInput) -> tuple[dict[str, str], str]:
    if not service_in_profile(req.service_id, req.profile_id):
        raise HTTPException(422, "服务不属于所选 Profile")
    if service_profile_id(req.service_id) != req.profile_id:
        raise HTTPException(422, "服务的 Profile 归属不唯一")
    service = get_service(req.service_id) or {}
    if req.capability_id and req.capability_id not in {
        item.get("id") for item in service.get("capabilities", [])
    }:
        raise HTTPException(422, "能力点不属于所选服务")
    if req.source_type == "official_doc":
        if not _official_url(req.url):
            raise HTTPException(422, "只接受 AWS 官方 HTTPS 文档链接")
        if req.details:
            raise HTTPException(422, "官方正文只能由服务端抓取，不能手工伪造")
        return {}, ""
    if req.url and not _official_url(req.url):
        raise HTTPException(422, "案例引用链接必须是 AWS 官方 HTTPS 文档")
    if set(req.details) - set(_FIELDS) or any(
        not isinstance(value, str) or len(value) > 4000 for value in req.details.values()
    ):
        raise HTTPException(422, "案例字段无效或过长")
    details = {key: (req.details.get(key) or "").strip() for key in _FIELDS}
    content = "\n".join(f"{label}：{details[key]}" for key, label in zip(_FIELDS, _LABELS)
                        if details[key])
    if _SENSITIVE.search(req.title + " " + content):
        raise HTTPException(422, "请先移除邮箱、12 位账号 ID 或访问密钥等敏感信息")
    return details, content


def _serialize(entry: KnowledgeEntry) -> dict:
    document = KnowledgeDocument(f"managed:{entry.id}", entry.title, entry.source_type,
                                 entry.content, entry.service_id, entry.capability_id, entry.url)
    return {
        "id": entry.id, "profile_id": entry.profile_id, "service_id": entry.service_id,
        "capability_id": entry.capability_id, "source_type": entry.source_type,
        "title": entry.title, "url": entry.url, "content": entry.content,
        "details": entry.details or {}, "source_ticket_id": entry.source_ticket_id,
        "replaces_entry_id": entry.replaces_entry_id,
        "status": entry.status, "index_status": entry.index_status,
        "created_by": entry.created_by, "reviewed_by": entry.reviewed_by,
        "chunk_count": len(_chunk_document(document)) if entry.content else 0,
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else "",
    }


def _refresh_index(force: bool = False) -> str:
    load_knowledge_documents.cache_clear()
    try:
        was_cached = get_retriever.cache_info().currsize > 0
        retriever = get_retriever()
        if was_cached and retriever._collection is None:
            # A previous startup may have fallen back while the tunnel was down.
            retriever._init_chroma()
            result = retriever.rebuild_index(force=force) if retriever._collection is not None else {"backend": "keyword"}
        else:
            result = retriever.rebuild_index(force=force) if was_cached else {
                "backend": "chroma" if retriever._collection is not None else "keyword"
            }
        if result["backend"] == "chroma":
            with SessionLocal() as db:
                db.query(KnowledgeEntry).filter_by(status="published").update(
                    {KnowledgeEntry.index_status: "indexed"})
                db.commit()
            return "indexed"
        return "pending"
    except Exception:
        # BM25 reads the newly published corpus; old vector IDs are filtered by
        # load_knowledge_documents in the semantic search path.
        load_knowledge_documents.cache_clear()
        return "pending"


@router.get("")
def list_entries(profile_id: str = "", current: dict = Depends(get_current_user)) -> list[dict]:
    with SessionLocal() as db:
        query = db.query(KnowledgeEntry)
        if current.get("r") != "manager":
            query = query.filter_by(created_by=current["uid"])
            profile_id = db.get(User, current["uid"]).current_profile
        if profile_id:
            query = query.filter_by(profile_id=profile_id)
        return [_serialize(item) for item in query.order_by(KnowledgeEntry.created_at.desc()).limit(100)]


@router.post("", status_code=201)
def create_entry(req: KnowledgeInput, current: dict = Depends(get_current_user)) -> dict:
    details, content = _validate_input(req)
    if current.get("r") != "manager" and req.source_type != "case":
        raise HTTPException(403, "成员只能投稿案例")
    if req.replaces_entry_id and current.get("r") != "manager":
        raise HTTPException(403, "只有管理员可以建立知识版本")
    with SessionLocal() as db:
        if req.replaces_entry_id:
            predecessor = db.get(KnowledgeEntry, req.replaces_entry_id)
            if (not predecessor or predecessor.status != "published"
                    or predecessor.profile_id != req.profile_id
                    or predecessor.service_id != req.service_id
                    or predecessor.source_type != req.source_type):
                raise HTTPException(422, "被替换条目必须是同 Profile、同服务、同类型的已发布版本")
        if current.get("r") != "manager":
            user = db.get(User, current["uid"])
            if not user or user.current_profile != req.profile_id or not req.source_ticket_id:
                raise HTTPException(403, "只能投稿当前 Profile 的已结案工单")
            ticket = db.get(TicketSession, req.source_ticket_id)
            if (not ticket or ticket.user_id != current["uid"] or ticket.status != "closed"
                    or ticket.service_id != req.service_id
                    or record_profile_id(ticket) != req.profile_id):
                raise HTTPException(404, "已结案工单不存在")
        entry = KnowledgeEntry(
            profile_id=req.profile_id, service_id=req.service_id,
            capability_id=req.capability_id, source_type=req.source_type,
            title=req.title.strip(), url=req.url, details=details,
            content=content, source_ticket_id=req.source_ticket_id,
            replaces_entry_id=req.replaces_entry_id,
            status="draft" if current.get("r") == "manager" else "submitted",
            created_by=current["uid"],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return _serialize(entry)


@router.put("/{entry_id}")
def update_entry(entry_id: str, req: KnowledgeInput,
                 current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    details, content = _validate_input(req)
    with SessionLocal() as db:
        entry = db.get(KnowledgeEntry, entry_id)
        if not entry:
            raise HTTPException(404, "知识条目不存在")
        if entry.status not in {"draft", "submitted"}:
            raise HTTPException(409, "已发布或下架的条目不可直接修改，请创建新版本")
        entry.profile_id, entry.service_id = req.profile_id, req.service_id
        entry.capability_id, entry.source_type = req.capability_id, req.source_type
        entry.title, entry.url = req.title.strip(), req.url
        entry.details, entry.content = details, content
        entry.source_ticket_id = req.source_ticket_id
        if req.replaces_entry_id:
            predecessor = db.get(KnowledgeEntry, req.replaces_entry_id)
            if (not predecessor or predecessor.status != "published" or predecessor.id == entry.id
                    or predecessor.profile_id != req.profile_id or predecessor.service_id != req.service_id
                    or predecessor.source_type != req.source_type):
                raise HTTPException(422, "被替换条目必须是同范围的已发布版本")
        entry.replaces_entry_id = req.replaces_entry_id
        db.commit()
        db.refresh(entry)
        return _serialize(entry)


@router.post("/{entry_id}/capture")
def capture_official(entry_id: str, current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    with SessionLocal() as db:
        entry = db.get(KnowledgeEntry, entry_id)
        if not entry or entry.source_type != "official_doc":
            raise HTTPException(404, "官方文档草稿不存在")
        if entry.status != "draft" or not _official_url(entry.url):
            raise HTTPException(409, "只能抓取尚未发布的有效官方文档草稿")
        resolved_url, excerpt = preferred_official_source(entry.url)
        if not _official_url(resolved_url) or len(excerpt.strip()) < 100:
            raise HTTPException(422, "官方页面不可访问或正文不足，未写入知识库")
        entry.content = excerpt.strip()
        entry.details = {"source_url": entry.url,
                         "sha256": hashlib.sha256(entry.content.encode()).hexdigest(),
                         "captured_at": datetime.now(timezone.utc).isoformat()}
        entry.url = resolved_url
        db.commit()
        db.refresh(entry)
        return _serialize(entry)


@router.post("/{entry_id}/publish")
def publish_entry(entry_id: str, current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    with SessionLocal() as db:
        entry = db.get(KnowledgeEntry, entry_id)
        if not entry:
            raise HTTPException(404, "知识条目不存在")
        if entry.status not in {"draft", "submitted"}:
            raise HTTPException(409, "条目当前不可发布")
        if entry.source_type == "case":
            if any(len((entry.details or {}).get(key, "").strip()) < 8 for key in _FIELDS):
                raise HTTPException(422, "案例发布前需补齐现象、排查、根因、方案和验证")
        elif (len(entry.content.strip()) < 100 or not _official_url(entry.url)
              or not (entry.details or {}).get("sha256")
              or hashlib.sha256(entry.content.encode()).hexdigest() != entry.details["sha256"]):
            raise HTTPException(422, "请先抓取并预览有效的官方正文")
        published = db.query(KnowledgeEntry).filter_by(
            profile_id=entry.profile_id, service_id=entry.service_id,
            source_type=entry.source_type, status="published").all()
        content_hash = hashlib.sha256(entry.content.strip().encode()).hexdigest()
        for other in published:
            if other.id == entry.replaces_entry_id:
                continue
            if (entry.source_type == "official_doc" and entry.url == other.url) or (
                hashlib.sha256(other.content.strip().encode()).hexdigest() == content_hash
            ):
                raise HTTPException(409, f"已有相同的已发布资料：{other.id}；请先核对版本，必要时下架旧条目")
        if entry.replaces_entry_id:
            predecessor = db.get(KnowledgeEntry, entry.replaces_entry_id)
            if not predecessor or predecessor.status != "published":
                raise HTTPException(409, "旧版本已不在发布状态，请刷新后重试")
            predecessor.status, predecessor.index_status = "archived", "pending"
        entry.status, entry.index_status, entry.reviewed_by = "published", "pending", current["uid"]
        db.add(AdminAudit(actor_id=current["uid"], target_id=entry.id,
                          action="publish_knowledge", detail=f"{entry.service_id}:{entry.source_type}"))
        db.commit()
        entry.index_status = _refresh_index()
        db.commit()
        db.refresh(entry)
        return _serialize(entry)


@router.post("/{entry_id}/archive")
def archive_entry(entry_id: str, current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    with SessionLocal() as db:
        entry = db.get(KnowledgeEntry, entry_id)
        if not entry:
            raise HTTPException(404, "知识条目不存在")
        if entry.status == "archived":
            raise HTTPException(409, "条目已下架")
        entry.status, entry.index_status = "archived", "pending"
        db.add(AdminAudit(actor_id=current["uid"], target_id=entry.id,
                          action="archive_knowledge", detail=entry.service_id))
        db.commit()
        entry.index_status = _refresh_index()
        db.commit()
        db.refresh(entry)
        return _serialize(entry)


@router.post("/reindex")
def reindex_knowledge(current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    return {"index_status": _refresh_index(force=True)}


@router.get("/coverage")
def knowledge_coverage_report(current: dict = Depends(get_current_user)) -> dict:
    _manager(current)
    return knowledge_coverage()
