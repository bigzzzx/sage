"""Evidence-based troubleshooting practice. No hidden answer is sent before submission."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.db import SessionLocal
from app.models import PracticeRun
from app.services.profile_scope import current_profile_id, service_in_profile, service_profile_id
from sqlalchemy import and_, or_

router = APIRouter(prefix="/api/practice", tags=["practice"])
SCENARIO_DIR = Path(__file__).resolve().parents[3] / "data" / "scenarios"


def _load_scenario(scenario_id: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", scenario_id):
        raise HTTPException(404, "场景不存在")
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if not path.is_file():
        raise HTTPException(404, "场景不存在")
    scenario = json.loads(path.read_text(encoding="utf-8"))
    if scenario.get("id") != scenario_id:
        raise HTTPException(500, "场景文件 ID 不一致")
    return scenario


def _public_scenario(scenario: dict) -> dict:
    return {key: scenario[key] for key in ("id", "service_id", "title", "level", "brief", "objective")}


def _run(db, run_id: str, user_id: str) -> PracticeRun:
    run = db.get(PracticeRun, run_id)
    profile_id = current_profile_id(db, user_id)
    recorded = (run.profile_id or service_profile_id(_load_scenario(run.scenario_id)["service_id"])) if run else None
    if not run or run.user_id != user_id or recorded != profile_id:
        raise HTTPException(404, "练习记录不存在")
    return run


def _run_response(run: PracticeRun, scenario: dict) -> dict:
    inspected = set(run.inspected_tools or [])
    return {
        "run_id": run.id,
        "scenario": {**_public_scenario(scenario), "tools": [
            {"id": tool["id"], "label": tool["label"],
             **({"evidence": tool["evidence"]} if tool["id"] in inspected else {})}
            for tool in scenario["tools"]
        ]},
        "inspected_tools": run.inspected_tools or [],
        "status": run.status,
        "answer": run.answer if run.status == "submitted" else "",
        "feedback": run.feedback if run.status == "submitted" else None,
    }


class StartRequest(BaseModel):
    scenario_id: str


class InspectRequest(BaseModel):
    tool_id: str


class SubmitRequest(BaseModel):
    answer: str = Field(min_length=20, max_length=5000)


@router.get("/scenarios")
def list_scenarios(current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        profile_id = current_profile_id(db, current["uid"])
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        scenario = _load_scenario(path.stem)
        if service_in_profile(scenario["service_id"], profile_id):
            scenarios.append(_public_scenario(scenario))
    return {"scenarios": scenarios}


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, current: dict = Depends(get_current_user)) -> dict:
    scenario = _load_scenario(scenario_id)
    with SessionLocal() as db:
        if not service_in_profile(scenario["service_id"], current_profile_id(db, current["uid"])):
            raise HTTPException(404, "场景不存在")
    return {**_public_scenario(scenario), "tools": [
        {"id": tool["id"], "label": tool["label"]} for tool in scenario["tools"]
    ]}


@router.post("/runs", status_code=201)
def start_run(req: StartRequest, current: dict = Depends(get_current_user)) -> dict:
    scenario = _load_scenario(req.scenario_id)
    with SessionLocal() as db:
        profile_id = current_profile_id(db, current["uid"])
        if not service_in_profile(scenario["service_id"], profile_id):
            raise HTTPException(404, "场景不存在")
        run = PracticeRun(user_id=current["uid"], profile_id=profile_id,
                          scenario_id=scenario["id"], inspected_tools=[])
        db.add(run)
        db.commit()
        db.refresh(run)
        return _run_response(run, scenario)


@router.get("/runs")
def list_runs(current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        profile_id = current_profile_id(db, current["uid"])
        legacy_ids = [scenario["id"] for path in SCENARIO_DIR.glob("*.json")
                      if (scenario := _load_scenario(path.stem)) and
                      service_profile_id(scenario["service_id"]) == profile_id]
        rows = (db.query(PracticeRun).filter_by(user_id=current["uid"]).filter(
                    or_(PracticeRun.profile_id == profile_id,
                        and_(or_(PracticeRun.profile_id.is_(None), PracticeRun.profile_id == ""),
                             PracticeRun.scenario_id.in_(legacy_ids))))
                .order_by(PracticeRun.created_at.desc()).limit(20).all())
        return {"runs": [{"run_id": row.id, "scenario_id": row.scenario_id,
                "title": _load_scenario(row.scenario_id)["title"], "status": row.status,
                "score": (row.feedback or {}).get("score"),
                "created_at": row.created_at.isoformat() if row.created_at else ""}
                for row in rows]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        run = _run(db, run_id, current["uid"])
        return _run_response(run, _load_scenario(run.scenario_id))


@router.post("/runs/{run_id}/inspect")
def inspect_tool(run_id: str, req: InspectRequest, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        run = _run(db, run_id, current["uid"])
        if run.status != "in_progress":
            raise HTTPException(409, "练习已提交")
        scenario = _load_scenario(run.scenario_id)
        tool = next((item for item in scenario["tools"] if item["id"] == req.tool_id), None)
        if not tool:
            raise HTTPException(404, "证据工具不存在")
        run.inspected_tools = list(dict.fromkeys([*(run.inspected_tools or []), req.tool_id]))
        db.commit()
        return {"tool_id": req.tool_id, "evidence": tool["evidence"]}


def _evaluate(answer: str, inspected: list[str], scenario: dict) -> dict:
    """Transparent rubric, not an LLM judgment of technical correctness."""
    text = answer.lower()
    rubric = scenario["rubric"]
    checks = [{"name": item["name"], "passed":
        (not item.get("evidence_tool") or item["evidence_tool"] in inspected) and
        all(any(term.lower() in text for term in alternatives) for alternatives in item["all_of"])}
        for item in rubric]
    return {
        "score": round(sum(item["passed"] for item in checks) * 100 / len(checks)),
        "max_score": 100,
        "checks": checks,
        "reference": scenario["expected"],
        "note": "规则核对仅用于练习反馈，不等同于专家人工评分。",
    }


@router.post("/runs/{run_id}/submit")
def submit_run(run_id: str, req: SubmitRequest, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        run = _run(db, run_id, current["uid"])
        scenario = _load_scenario(run.scenario_id)
        if run.status == "submitted":
            return _run_response(run, scenario)
        if not run.inspected_tools:
            raise HTTPException(400, "请先查看至少一条证据")
        run.answer = req.answer.strip()
        run.feedback = _evaluate(run.answer, run.inspected_tools, scenario)
        run.status = "submitted"
        db.commit()
        db.refresh(run)
        return _run_response(run, scenario)
