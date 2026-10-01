"""Manager-facing, profile-scoped evidence summary. Never treat missing evidence as zero."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.db import SessionLocal
from app.models import Assessment, LearningTaskProgress, TicketSession, TrainingEnrollment, User
from app.services.assessment_summary import summarize_answers
from app.services.profile_scope import profile_filter
from app.services.taxonomy import get_profile_services


def build_team_dashboard(profile_id: str, days: int = 0, include_demo: bool = False,
                         enrolled_only: bool = False) -> dict:
    services = get_profile_services(profile_id)
    if not services:
        raise ValueError("未知的 Profile")
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    with SessionLocal() as db:
        members_query = db.query(User).filter(User.role == "member", User.is_active.is_(True))
        if not include_demo:
            members_query = members_query.filter(User.is_demo.is_(False))
        enrolled_ids = {row.user_id for row in db.query(TrainingEnrollment).filter_by(profile_id=profile_id).all()}
        if enrolled_only:
            members_query = members_query.filter(User.id.in_(enrolled_ids))
        members = members_query.order_by(User.username.asc()).all()
        ids = [m.id for m in members]
        assessments = []
        tickets = []
        if ids:
            aq = db.query(Assessment).filter(Assessment.user_id.in_(ids), profile_filter(Assessment, profile_id),
                                             func.coalesce(Assessment.record_origin, "user") != "agent_test")
            tq = db.query(TicketSession).filter(TicketSession.user_id.in_(ids), profile_filter(TicketSession, profile_id))
            if since:
                aq = aq.filter(Assessment.created_at >= since)
                tq = tq.filter(TicketSession.created_at >= since)
            assessments = aq.order_by(Assessment.created_at.desc(), Assessment.id.desc()).all()
            tickets = tq.order_by(TicketSession.created_at.desc(), TicketSession.id.desc()).all()

        by_member: dict[str, list[Assessment]] = {m.id: [] for m in members}
        ticket_counts = {m.id: 0 for m in members}
        for row in assessments:
            by_member[row.user_id].append(row)
        for row in tickets:
            ticket_counts[row.user_id] += 1
        plan_ids = [row.id for row in assessments if row.kind == "pre" and row.learning_plan]
        completed_progress = {}
        if plan_ids:
            progress = db.query(LearningTaskProgress).filter(
                LearningTaskProgress.assessment_id.in_(plan_ids),
                LearningTaskProgress.status == "completed").all()
            for row in progress:
                completed_progress[row.assessment_id] = completed_progress.get(row.assessment_id, 0) + 1

        output = []
        followups = []
        tested_services: set[str] = set()
        for member in members:
            records = by_member[member.id]
            latest = {}
            post_for_pre = {r.prev_assessment_id for r in records if r.kind == "post" and r.prev_assessment_id}
            for row in records:
                latest.setdefault(row.service_id, row)
            cells = []
            for service in services:
                row = latest.get(service["id"])
                summary = summarize_answers(row.questions_snapshot or [], row.question_results or []) if row else None
                state = "untested" if not row else ("observed" if summary["rating_reliable"] else "reference")
                if row:
                    tested_services.add(service["id"])
                cells.append({"service_id": service["id"], "service_name": service["name"],
                              "state": state, "score": round(summary["overall_avg"], 1) if summary else None,
                              "question_count": summary.get("question_count", 0) if summary else 0,
                              "assessment_id": row.id if row else None,
                              "assessed_at": row.created_at.isoformat() if row else None})
            latest_pre = {}
            for row in records:
                if row.kind == "pre":
                    latest_pre.setdefault(row.service_id, row)
            open_plans = [row for row in latest_pre.values() if row.learning_plan and row.id not in post_for_pre]
            completed_tasks = [plan for plan in open_plans if
                               (task_count := sum(len(week.get("tasks", [])) for week in
                                                  (plan.learning_plan or {}).get("weekly_plan", []))) > 0
                               and completed_progress.get(plan.id, 0) >= task_count]
            if not any(c["state"] != "untested" for c in cells):
                followups.append({"user_id": member.id, "username": member.username,
                                  "reason": "本时间范围内暂无测评", "priority": "info"})
            for plan in completed_tasks:
                followups.append({"user_id": member.id, "username": member.username,
                                  "reason": f"{plan.service_id} 计划已完成，待学后测", "priority": "action"})
            output.append({"user_id": member.id, "username": member.username,
                           "display_name": member.display_name, "services": cells,
                           "assessment_count": len(records), "ticket_count": ticket_counts[member.id],
                           "active_plan_count": len(open_plans)})
        return {"profile_id": profile_id, "days": days, "include_demo": include_demo,
                "members": output, "followups": followups,
                "metrics": {"members": len(output),
                            "enrolled_members": sum(m["user_id"] in enrolled_ids for m in output),
                            "assessed_members": sum(any(c["state"] != "untested" for c in m["services"]) for m in output),
                            "tested_services": len(tested_services), "total_services": len(services),
                            "active_plans": sum(m["active_plan_count"] for m in output)}}
