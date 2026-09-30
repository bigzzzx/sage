"""Offline, opt-in paired report-strategy experiment. Never writes production assessments.

Run from backend: python -m app.scripts.compare_report_strategies --output ../data/evals/runs/local.json
The JSON contains synthetic answers and model output; do not run on private user data.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time

from app.agents.common import safe_json_loads
from app.agents.diagnosis import run_diagnosis
from app.agents.orchestrator import _plan_issues
from app.agents.planning import run_planning
from app.schemas.assessment import KnowledgeGap, LearningPlan
from app.services.llm import capture_llm_usage, get_llm
from app.services.taxonomy import get_service

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = ROOT / "data" / "evals" / "report_cases.json"
ARMS = ("rules", "single_review", "dual_review", "debate", "budget_repeat")


def validate_cases(cases: list[dict]) -> None:
    if not cases or len({item["id"] for item in cases}) != len(cases):
        raise ValueError("Cases must be nonempty with unique IDs")
    for case in cases:
        if case["service_id"] != "glue" or not 1 <= case["study_days"] <= 7 or not 30 <= case["minutes_per_day"] <= 180:
            raise ValueError(f"Invalid service or study budget: {case['id']}")
        questions = case["questions"]
        ids = {q["id"] for q in questions}
        if not questions or len(ids) != len(questions) or ids != set(case["answers"]):
            raise ValueError(f"Questions/answers mismatch: {case['id']}")
        if ids != {r["question_id"] for r in case["question_results"]}:
            raise ValueError(f"Questions/results mismatch: {case['id']}")


def _render_report(gaps: list[KnowledgeGap], plan: LearningPlan) -> str:
    return json.dumps({"diagnosis": [g.model_dump() for g in gaps],
                       "learning_plan": plan.model_dump()}, ensure_ascii=False)


def _review(case: dict, gaps: list[KnowledgeGap], plan: LearningPlan, model: str,
            role: str, prior: list[dict] | None = None) -> dict:
    evidence = {"overall_level": case.get("overall_level"),
                "questions": case["questions"], "answers": case["answers"],
                "question_results": case["question_results"],
                "study_days": case["study_days"], "minutes_per_day": case["minutes_per_day"]}
    instruction = {
        "general": "独立核对诊断证据、技术事实与引用支持，并检查学习任务是否切中缺口、可执行且能验证。",
        "evidence": "独立核对诊断是否被答题证据支持，以及技术陈述是否由给定事实/来源支持。",
        "teaching": "独立核对学习任务是否切中诊断、步骤与验证是否可执行、时间是否现实。",
    }[role]
    prompt = (f"你是 AWS Glue 报告审稿人。{instruction}只用给定证据；来源链接存在不等于事实正确。"
              "overall_level 是已给定的测评等级，不得误报为报告臆测。"
              "docs.aws.amazon.com 和 docs.amazonaws.cn 都可能是官方文档；域名不同本身不是引用错误，必须核对相邻断言。"
              "S3 VPC Endpoint 不能替代 NAT 连接任意公网 API；未在 AWS 实测的任务不可声称已验证。"
              "不确定的技术事实标记待人工核验。输出纯 JSON 对象，只有 issues 数组；"
              "每项 issue 含 category（fact/diagnosis/citation/actionability）、location、problem、evidence、suggestion。"
              "证据不足不得声称已证实错误。\n"
              f"答题资料：{json.dumps(evidence, ensure_ascii=False)}\n报告：{_render_report(gaps, plan)}")
    if prior is not None:
        prompt += ("\n其他审稿意见（可能有错，逐条挑战其证据和优先级；不是照单全收）："
                   + json.dumps(prior, ensure_ascii=False))
    raw = get_llm().chat([{"role": "system", "content": "独立审稿，严格 JSON。"},
                          {"role": "user", "content": prompt}], temperature=0, model=model)
    parsed = safe_json_loads(raw, {})
    if not isinstance(parsed, dict) or not isinstance(parsed.get("issues"), list):
        raise ValueError("Review output has no issues array")
    issues = []
    for item in parsed["issues"][:12]:
        if (isinstance(item, dict) and item.get("category") in
                {"fact", "diagnosis", "citation", "actionability"} and
                all(isinstance(item.get(key), str) for key in ("location", "problem", "evidence", "suggestion"))):
            issues.append({key: item[key][:500] for key in
                           ("category", "location", "problem", "evidence", "suggestion")})
    return {"role": role, "issues": issues}


def _reviews_for_arm(arm: str, case: dict, gaps: list[KnowledgeGap],
                     plan: LearningPlan, model: str) -> list[dict]:
    if arm == "rules":
        return []
    if arm == "single_review":
        return [_review(case, gaps, plan, model, "general")]
    first = [_review(case, gaps, plan, model, role) for role in ("evidence", "teaching")]
    if arm == "dual_review":
        return first
    if arm == "debate":
        return first + [_review(case, gaps, plan, model, role, [first[1 - idx]])
                        for idx, role in enumerate(("evidence", "teaching"))]
    # Same number of reviewer calls as debate, but no cross-review information.
    return first + [_review(case, gaps, plan, model, role)
                    for role in ("evidence", "teaching")]


def _usage_summary(records: list[dict], price_in: float | None,
                   price_out: float | None) -> dict:
    known = all(isinstance(row.get(key), int) for row in records
                for key in ("prompt_tokens", "completion_tokens"))
    input_tokens = sum(row["prompt_tokens"] for row in records) if known else None
    output_tokens = sum(row["completion_tokens"] for row in records) if known else None
    cost = (round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)
            if known and price_in is not None and price_out is not None else None)
    return {"api_attempts": len(records), "failed_attempts": sum(r["status"] != "ok" for r in records),
            "prompt_tokens": input_tokens, "completion_tokens": output_tokens,
            "estimated_cost": cost, "currency": "USD" if cost is not None else None,
            "pricing_per_million": {"input": price_in, "output": price_out} if cost is not None else None}


def _merge_usage(shared: dict, incremental: dict) -> dict:
    merged = {"api_attempts": shared["api_attempts"] + incremental["api_attempts"],
              "failed_attempts": shared["failed_attempts"] + incremental["failed_attempts"],
              "currency": shared["currency"] or incremental["currency"],
              "pricing_per_million": shared["pricing_per_million"] or incremental["pricing_per_million"]}
    for field in ("prompt_tokens", "completion_tokens", "estimated_cost"):
        a, b = shared[field], incremental[field]
        merged[field] = round(a + b, 6) if a is not None and b is not None else None
    return merged


def _run_arm(arm: str, case: dict, svc: dict, gaps: list[KnowledgeGap],
             draft: LearningPlan, model: str) -> dict:
    plan = deepcopy(draft)
    deterministic = _plan_issues(plan, gaps, study_days=case["study_days"],
                                 minutes_per_day=case["minutes_per_day"])
    reviews = _reviews_for_arm(arm, case, gaps, draft, model)
    issues = [issue for review in reviews for issue in review["issues"]]
    # Give each independent reviewer a chance to influence the same-sized revision prompt.
    selected, seen = [], set()
    for index in range(max((len(review["issues"]) for review in reviews), default=0)):
        for review in reviews:
            if index >= len(review["issues"]):
                continue
            issue = review["issues"][index]
            key = (issue["category"], issue["location"], issue["problem"])
            if key not in seen:
                selected.append(issue)
                seen.add(key)
            if len(selected) >= 8:
                break
        if len(selected) >= 8:
            break
    revised = False
    revision_status = "not_requested"
    if arm != "rules" and (issues or deterministic):
        feedback = json.dumps({"hard_rule_issues": deterministic,
                               "review_issues": selected}, ensure_ascii=False)
        candidate, step, _ = run_planning(
            service_name=svc["name"], overall_level=case["overall_level"],
            capability_scores={}, gaps=gaps, svc=svc, model=model,
            review_feedback=feedback, study_days=case["study_days"],
            minutes_per_day=case["minutes_per_day"])
        revision_status = step.status
        candidate_issues = _plan_issues(candidate, gaps, study_days=case["study_days"],
                                        minutes_per_day=case["minutes_per_day"])
        if step.status == "ok" and candidate.weekly_plan and len(candidate_issues) <= len(deterministic):
            plan, revised = candidate, True
    return {"report": {"diagnosis": [g.model_dump() for g in gaps],
                        "learning_plan": plan.model_dump()},
            "review_issues": issues, "deterministic_issues": _plan_issues(
                plan, gaps, study_days=case["study_days"], minutes_per_day=case["minutes_per_day"]),
            "review_calls": len(reviews), "revision_status": revision_status,
            "revision_applied": revised}


def run_case(case: dict, model: str, price_in: float | None,
             price_out: float | None, previous: dict | None = None) -> dict:
    svc = get_service(case["service_id"])
    if not svc:
        raise ValueError("Glue taxonomy unavailable")
    saved = (previous or {}).get("shared_generation")
    if saved:
        gaps = [KnowledgeGap(**item) for item in saved["diagnosis"]]
        draft = LearningPlan(**saved["draft"])
        shared_ms, shared_usage = saved["elapsed_ms"], saved["usage"]
    else:
        with capture_llm_usage() as shared_records:
            started = time.perf_counter()
            gaps, trace = run_diagnosis(case["service_id"], svc["name"], svc,
                                        case["questions"], case["answers"],
                                        case["question_results"], model=model)
            if any(step.status == "failed" for step in trace) or not gaps:
                raise RuntimeError(f"Shared diagnosis failed or empty: {case['id']}")
            draft, step, _ = run_planning(svc["name"], case["overall_level"], {}, gaps,
                                          svc, model=model, study_days=case["study_days"],
                                          minutes_per_day=case["minutes_per_day"])
            if step.status != "ok" or not draft.weekly_plan:
                raise RuntimeError(f"Shared draft failed: {case['id']}")
            shared_ms = round((time.perf_counter() - started) * 1000)
        shared_usage = _usage_summary(shared_records, price_in, price_out)
    variants = dict((previous or {}).get("variants", {}))
    for arm in ARMS:
        if "report" in variants.get(arm, {}):
            continue
        print(f"case={case['id']} arm={arm} started", flush=True)
        with capture_llm_usage() as records:
            started = time.perf_counter()
            try:
                result = _run_arm(arm, case, svc, gaps, draft, model)
            except Exception as exc:
                result = {"error_type": type(exc).__name__,
                          "http_status": getattr(exc, "status_code", None)}
            elapsed_ms = round((time.perf_counter() - started) * 1000)
        incremental_usage = _usage_summary(records, price_in, price_out)
        result.update(elapsed_ms=shared_ms + elapsed_ms,
                      incremental_elapsed_ms=elapsed_ms,
                      usage=_merge_usage(shared_usage, incremental_usage),
                      incremental_usage=incremental_usage)
        variants[arm] = result
        print(f"case={case['id']} arm={arm} status={'ok' if 'report' in result else 'failed'}", flush=True)
    return {"case_id": case["id"], "shared_generation": {
        "elapsed_ms": shared_ms,
        "usage": shared_usage,
        "diagnosis": [gap.model_dump() for gap in gaps],
        "draft": draft.model_dump()}, "variants": variants}


def make_blind_template(results: list[dict], seed: int) -> dict:
    rows = []
    for case in results:
        for arm, variant in case.get("variants", {}).items():
            if "report" not in variant:
                continue
            opaque_id = hashlib.sha256(f"{seed}:{case['case_id']}:{arm}".encode()).hexdigest()[:16]
            rows.append({"report_id": opaque_id, "case_id": case["case_id"],
                         "report": variant["report"],
                         "annotations": []})
    random.Random(seed).shuffle(rows)
    return {"rubric": "docs/REPORT_COMPARISON.md", "blind_reports": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="deepseek-flash",
        help="Model ID; defaults to the lower-cost DeepSeek Flash model",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Retry only failed/missing arms from existing output")
    args = parser.parse_args()
    if args.output.exists() and not args.resume:
        parser.error("Output already exists; use a new path to preserve prior experiment")
    if (args.input_usd_per_million is None) != (args.output_usd_per_million is None):
        parser.error("Provide both price flags or neither")
    if any(v is not None and v < 0 for v in (args.input_usd_per_million, args.output_usd_per_million)):
        parser.error("Prices must be nonnegative")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    validate_cases(cases)
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.limit:
        cases = cases[:args.limit]
    previous_by_id = {}
    fixture_hash = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    if args.resume:
        if not args.output.exists():
            parser.error("--resume requires an existing output")
        old = json.loads(args.output.read_text(encoding="utf-8"))
        if old["model"] != args.model or old["fixture_sha256"] != fixture_hash or old["seed"] != args.seed:
            parser.error("Model, fixture, or seed differs from saved run")
        if old.get("complete") and all(
            all("report" in case.get("variants", {}).get(arm, {}) for arm in ARMS)
            for case in old["cases"]):
            parser.error("Run is already complete; resume would replace its blind template")
        previous_by_id = {item["case_id"]: item for item in old["cases"]}
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        print(f"case={case['id']} shared_generation started", flush=True)
        try:
            results.append(run_case(case, args.model, args.input_usd_per_million,
                                    args.output_usd_per_million,
                                    previous=previous_by_id.get(case["id"])))
        except Exception as exc:
            results.append({"case_id": case["id"], "error_type": type(exc).__name__,
                            "http_status": getattr(exc, "status_code", None)})
        output = {"created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
                  "fixture_sha256": fixture_hash,
                  "fixture_path": str(args.cases), "seed": args.seed, "cases": results,
                  "complete": len(results) == len(cases) and all(
                      all("report" in row.get("variants", {}).get(arm, {}) for arm in ARMS)
                      for row in results),
                  "warning": "Synthetic inputs; model critiques are not human quality labels. Shared diagnosis is identical across arms."}
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        template = make_blind_template(results, args.seed)
        args.output.with_suffix(".blind.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"case={case['id']} saved", flush=True)
    print(json.dumps({"result": str(args.output), "blind_template": str(args.output.with_suffix('.blind.json')),
                      "complete_cases": sum("variants" in row for row in results),
                      "blind_reports": len(template["blind_reports"])}, ensure_ascii=False))
    return 0 if len(results) == sum("variants" in row for row in results) and all(
        all("report" in variant for variant in row["variants"].values())
        for row in results if "variants" in row) else 1


if __name__ == "__main__":
    raise SystemExit(main())
