"""Evaluate configured models against a small, sourced Glue fact set and the app's open-answer scorer.

Run from backend: python -m app.scripts.evaluate_glue_quality
This is a smoke benchmark, not an AWS certification or a production quality SLA.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from app.services.assessment import _score_open_question
from app.services.llm import get_available_models, get_llm

FACTS_PATH = Path(__file__).resolve().parents[3] / "data" / "evals" / "glue_public_facts.json"

SCORING_QUESTION = {
    "difficulty": "L2",
    "question": "Glue Job 已配置 VPC Connection，能访问私有 RDS，但无法访问公网 API。说明网络原因和修复方法。",
    "scoring_rubric": ["说明 Glue ENI 只有私有 IP", "指出公有子网加 IGW 不足够", "说明配置 NAT 出口并检查路由和安全组", "区分 S3 VPC endpoint 与公网 API 出口"],
    "reference_answer": "Glue VPC ENI 仅有私有 IP，即便子网有 Internet Gateway 也不能直接访问公网。为需要公网 API 的 Glue Job 配置 NAT 网关或等效 NAT 出口，并检查子网路由、安全组、网络 ACL；访问 S3 可以使用 S3 VPC endpoint，不等同于通用公网出口。",
}
STRONG_ANSWER = "Glue 在 VPC 中创建的 ENI 只有私有 IP，公有子网加 IGW 不能让它直接上网。应使用私有子网路由到 NAT 网关，检查 NAT 所在子网的 IGW 路由、Glue 子网路由、安全组出站和网络 ACL；S3 可单独使用 VPC endpoint，但公网 API 仍需要 NAT 等出口。"
WEAK_ANSWER = "给 Glue Job 配置更大的 G.2X worker 就能访问公网。"


def _strip_fence(value: str) -> str:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        value = value.rsplit("```", 1)[0]
    return value.strip()


def evaluate(model: str, facts: list[dict], repeats: int) -> dict:
    rng = random.Random(20260923)
    request = []
    expected_answers = {}
    for item in facts:
        options = item["options"].copy()
        correct_text = options["ABCD".index(item["answer"])]
        rng.shuffle(options)
        expected_answers[item["id"]] = "ABCD"[options.index(correct_text)]
        request.append({"id": item["id"], "question": item["question"], "options": options})
    started = time.perf_counter()
    raw = get_llm().chat(
        [{"role": "system", "content": "回答 AWS Glue 单选题；只输出 JSON 对象，格式为 {\"answers\":{\"题目id\":\"A/B/C/D\"}}。不要解释。"},
         {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
        temperature=0, model=model,
    )
    answer_ms = round((time.perf_counter() - started) * 1000)
    payload = json.loads(_strip_fence(raw))
    answers = payload.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("模型未返回 answers 对象")
    rows = []
    for item in facts:
        actual = str(answers.get(item["id"], "")).strip().upper()
        rows.append({"id": item["id"], "actual": actual, "correct": actual == expected_answers[item["id"]]})

    strong_scores, strong_ms = [], []
    for _ in range(repeats):
        started = time.perf_counter()
        strong_scores.append(_score_open_question(SCORING_QUESTION, STRONG_ANSWER, model=model)["avg_score"])
        strong_ms.append(round((time.perf_counter() - started) * 1000))
    started = time.perf_counter()
    weak_score = _score_open_question(SCORING_QUESTION, WEAK_ANSWER, model=model)["avg_score"]
    weak_ms = round((time.perf_counter() - started) * 1000)
    return {
        "model": model,
        "fact_accuracy": round(sum(row["correct"] for row in rows) / len(rows), 3),
        "fact_correct": sum(row["correct"] for row in rows),
        "fact_total": len(rows),
        "fact_answer_ms": answer_ms,
        "fact_rows": rows,
        "scoring_strong_repeats": strong_scores,
        "scoring_repeat_range": round(max(strong_scores) - min(strong_scores), 1),
        "scoring_weak": weak_score,
        "scoring_order_correct": min(strong_scores) > weak_score,
        "scoring_strong_mean_ms": round(statistics.mean(strong_ms)),
        "scoring_weak_ms": weak_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        help="Model IDs; defaults to the configured model only (DeepSeek Flash by default)",
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 10:
        parser.error("--repeats must be between 1 and 10")
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    if not facts or len({item["id"] for item in facts}) != len(facts):
        raise ValueError("Fact set empty or IDs duplicated")
    available = get_available_models()
    # Keep normal test runs on the configured low-cost model. Comparing Pro is
    # still available, but must be an explicit --models choice.
    models = args.models or ([available["default_model"]] if available["default_model"] else [])
    if not models:
        raise ValueError("No configured models")
    if any(model not in available["models"] for model in models):
        raise ValueError("Only available model IDs may be evaluated")
    results = []
    for model in models:
        try:
            results.append(evaluate(model, facts, args.repeats))
        except Exception as exc:
            # Provider exceptions may contain request details; do not print them.
            results.append({"model": model, "error_type": type(exc).__name__})
    print(json.dumps({"fixture": str(FACTS_PATH), "results": results}, ensure_ascii=False, indent=2))
    return 1 if any("error_type" in result for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
