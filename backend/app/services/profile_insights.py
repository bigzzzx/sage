"""Evidence-first, current-profile-only data for the learner's profile page."""
from __future__ import annotations

from collections import Counter, defaultdict

from app.db import SessionLocal
from app.models import Assessment, LearningTaskProgress, TicketSession
from app.services.assessment import _assessment_scoring_version
from app.services.assessment_summary import summarize_answers
from app.services.profile_scope import current_profile_id, profile_filter
from app.services.taxonomy import get_full_taxonomy
from app.services.ticket_simulation import DIMENSIONS


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _scored_capabilities(assessment: Assessment) -> dict[str, dict]:
    results = {item.get("question_id"): item for item in (assessment.question_results or [])
               if isinstance(item, dict)}
    values: dict[str, list[float]] = defaultdict(list)
    for question in assessment.questions_snapshot or []:
        if not isinstance(question, dict) or not question.get("dimension_id"):
            continue
        result = results.get(question.get("id"))
        if not result or result.get("total_score") is None:
            continue
        try:
            raw = float(result["total_score"])
        except (TypeError, ValueError):
            continue
        score = raw if question.get("type") == "choice" else raw / 5
        values[str(question["dimension_id"])].append(max(0.0, min(5.0, score)))
    return {key: {"score": round(sum(scores) / len(scores), 2), "sample_count": len(scores)}
            for key, scores in values.items()}


def _blueprint(assessment: Assessment) -> Counter[tuple[str, str, str]]:
    return Counter((str(q.get("dimension_id", "")), str(q.get("difficulty", "")).upper(),
                    str(q.get("type", ""))) for q in (assessment.questions_snapshot or [])
                   if isinstance(q, dict))


def _same_items(pre: Assessment, post: Assessment) -> bool:
    """AI-generated questions are not equated merely because their blueprint matches."""
    def items(row):
        return Counter((str(q.get("id", "")), str(q.get("question", "")))
                       for q in (row.questions_snapshot or []) if isinstance(q, dict))
    return bool(items(pre)) and items(pre) == items(post)


def _trend(pre: Assessment, post: Assessment) -> dict:
    before = summarize_answers(pre.questions_snapshot or [], pre.question_results or [])
    after = summarize_answers(post.questions_snapshot or [], post.question_results or [])
    version_before = _assessment_scoring_version(pre.question_results or [])
    version_after = _assessment_scoring_version(post.question_results or [])
    reasons = []
    if not before["rating_reliable"] or not after["rating_reliable"]:
        reasons.append("至少一次测评样本不足")
    if version_before != version_after or version_before == "legacy_or_mixed":
        reasons.append("评分版本不同")
    if _blueprint(pre) != _blueprint(post) or not _blueprint(pre):
        reasons.append("能力点、难度或题型覆盖不同")
    if not _same_items(pre, post):
        reasons.append("没有相同或已校准的题目，不能排除出题差异")
    comparable = not reasons
    return {"pre_assessment_id": pre.id, "post_assessment_id": post.id,
            "service_id": pre.service_id, "pre_score": before["overall_avg"],
            "post_score": after["overall_avg"],
            "delta": round(after["overall_avg"] - before["overall_avg"], 2) if comparable else None,
            "comparable": comparable, "reason": "；".join(reasons),
            "pre_count": before["question_count"], "post_count": after["question_count"],
            "created_at": _iso(post.created_at)}


def _ticket_feedback(tickets: list[TicketSession]) -> list[dict]:
    reports = [(row, row.report) for row in tickets if row.status == "closed"
               and isinstance(row.report, dict) and isinstance(row.report.get("dimensions"), list)]
    version = next((report.get("scoring_version") for _, report in reports
                    if report.get("scoring_version")), None)
    out = []
    for key, label in DIMENSIONS.items():
        observations = []
        for row, report in reports:
            if report.get("scoring_version") != version:
                continue
            item = next((item for item in report["dimensions"]
                         if isinstance(item, dict) and item.get("id") == key), None)
            if not item or item.get("not_observed") or not isinstance(item.get("score"), (int, float)):
                continue
            observations.append((row.id, item))
        out.append({"id": key, "label": label,
                    "score": round(sum(item["score"] for _, item in observations) / len(observations), 1)
                    if observations else None,
                    "sample_count": len(observations),
                    "latest_ticket_id": observations[0][0] if observations else None,
                    "next_step": observations[0][1].get("next_step", "") if observations else ""})
    return out


def get_user_profile_insights(user_id: str) -> dict:
    with SessionLocal() as db:
        profile_id = current_profile_id(db, user_id)
        if not profile_id:
            return {"profile_id": "", "profile_name": "", "services": [], "plans": [],
                    "ticket_dimensions": [], "ticket_count": 0, "trends": [], "recent_assessments": []}
        track = next((t for t in get_full_taxonomy()["tracks"] if t["id"] == profile_id), None)
        if not track:
            return {"profile_id": profile_id, "profile_name": profile_id, "services": [], "plans": [],
                    "ticket_dimensions": [], "ticket_count": 0, "trends": [], "recent_assessments": []}
        assessments = (db.query(Assessment).filter(Assessment.user_id == user_id,
                                                   profile_filter(Assessment, profile_id))
                       .order_by(Assessment.created_at.desc(), Assessment.id.desc()).all())
        tickets = (db.query(TicketSession).filter(TicketSession.user_id == user_id,
                                                  profile_filter(TicketSession, profile_id))
                   .order_by(TicketSession.updated_at.desc(), TicketSession.id.desc()).all())
        evidence = [row for row in assessments if row.record_origin != "agent_test"]
        by_service: dict[str, list[Assessment]] = defaultdict(list)
        by_id = {row.id: row for row in evidence}
        for row in evidence:
            by_service[row.service_id].append(row)
        services = []
        for service in track["services"]:
            records = by_service.get(service["id"], [])
            latest = records[0] if records else None
            summary = summarize_answers(latest.questions_snapshot or [], latest.question_results or []) if latest else None
            seen = {}
            for record in records:
                for cap_id, score in _scored_capabilities(record).items():
                    if cap_id not in seen:
                        seen[cap_id] = {**score, "assessment_id": record.id,
                                        "assessed_at": _iso(record.created_at),
                                        "scoring_version": _assessment_scoring_version(record.question_results or [])}
            capabilities = [{"id": cap["id"], "name": cap["name"], **seen.get(cap["id"],
                             {"score": None, "sample_count": 0, "assessment_id": None,
                              "assessed_at": "", "scoring_version": None})}
                            for cap in service.get("capabilities", [])]
            services.append({"service_id": service["id"], "service_name": service["name"],
                             "icon": service.get("icon", ""), "capabilities": capabilities,
                             "tested_capability_count": sum(cap["score"] is not None for cap in capabilities),
                             "latest_assessment": {"id": latest.id, "score": summary["overall_avg"] if summary["question_count"] else None,
                                                   "rating_reliable": summary["rating_reliable"],
                                                   "question_count": summary["question_count"],
                                                   "created_at": _iso(latest.created_at)} if latest else None})
        plans = []
        for service in track["services"]:
            pres = [row for row in by_service.get(service["id"], []) if row.kind == "pre"]
            if not pres or not pres[0].learning_plan:
                continue
            pre = pres[0]
            if any(row.kind == "post" and row.prev_assessment_id == pre.id for row in evidence):
                continue
            weeks = pre.learning_plan.get("weekly_plan") or []
            task_keys = {(wi, ti) for wi, week in enumerate(weeks)
                         for ti, _ in enumerate(week.get("tasks") or [])}
            completed = set()
            if task_keys:
                completed = {(row.week_index, row.task_index) for row in
                             db.query(LearningTaskProgress).filter(
                                 LearningTaskProgress.user_id == user_id,
                                 LearningTaskProgress.assessment_id == pre.id,
                                 LearningTaskProgress.status.in_(["completed", "submitted", "verified"])).all()}
            plans.append({"assessment_id": pre.id, "service_name": service["name"],
                          "plan_name": pre.learning_plan.get("plan_name") or "学习计划",
                          "total_tasks": len(task_keys), "completed_tasks": len(task_keys & completed),
                          "review_status": (pre.plan_review or {}).get("status", "unknown"),
                          "created_at": _iso(pre.created_at)})
        plans.sort(key=lambda item: item["created_at"], reverse=True)
        trends = [_trend(by_id[row.prev_assessment_id], row) for row in evidence
                  if row.kind == "post" and row.prev_assessment_id in by_id
                  and by_id[row.prev_assessment_id].kind == "pre"
                  and by_id[row.prev_assessment_id].service_id == row.service_id]
        return {"profile_id": profile_id, "profile_name": track["name"], "services": services,
                "plans": plans, "ticket_dimensions": _ticket_feedback(tickets),
                "ticket_count": sum(row.status == "closed" for row in tickets),
                "trends": trends[:5],
                "recent_assessments": [{"assessment_id": row.id, "service_id": row.service_id,
                                        "kind": row.kind, "record_origin": row.record_origin or "user",
                                        "created_at": _iso(row.created_at)}
                                       for row in assessments[:3]]}
