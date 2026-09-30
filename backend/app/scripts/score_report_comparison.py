"""Score human labels only; never substitute model reviews for expert annotations.

Run from backend: python -m app.scripts.score_report_comparison --run PATH --blind PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics

from app.scripts.compare_report_strategies import ARMS

FIELDS = ("factual_error_count", "diagnosis_error_count", "citation_support",
          "task_actionability")


def operational_metrics(run: dict) -> dict:
    """Runtime data is valid without human labels; never emit quality scores here."""
    rows = {arm: [] for arm in ARMS}
    budget_match = []
    for case in run["cases"]:
        variants = case.get("variants", {})
        for arm in ARMS:
            variant = variants.get(arm, {})
            if "report" not in variant:
                continue
            usage = variant["usage"]
            rows[arm].append({"case_id": case["case_id"], "elapsed_ms": variant["elapsed_ms"],
                              "api_attempts": usage["api_attempts"],
                              "prompt_tokens": usage["prompt_tokens"],
                              "completion_tokens": usage["completion_tokens"],
                              "estimated_cost": usage["estimated_cost"]})
        if all("report" in variants.get(arm, {}) for arm in ("debate", "budget_repeat")):
            left = variants["debate"]["incremental_usage"]
            right = variants["budget_repeat"]["incremental_usage"]
            a = (left["prompt_tokens"] + left["completion_tokens"]
                 if all(isinstance(left[key], int) for key in ("prompt_tokens", "completion_tokens")) else None)
            b = (right["prompt_tokens"] + right["completion_tokens"]
                 if all(isinstance(right[key], int) for key in ("prompt_tokens", "completion_tokens")) else None)
            ratio = round(a / b, 3) if a is not None and b else None
            budget_match.append({"case_id": case["case_id"], "incremental_token_ratio": ratio,
                                 "within_20_percent": ratio is not None and 0.8 <= ratio <= 1.2,
                                 "review_calls_equal": variants["debate"].get("review_calls") ==
                                                       variants["budget_repeat"].get("review_calls")})
    return {"status": "runtime_only_not_human_quality", "model": run["model"],
            "case_count": len(run["cases"]), "complete": run.get("complete"),
            "by_arm": rows, "budget_match": budget_match}


def score(run: dict, blind: dict) -> dict:
    if run.get("complete") is False or any(
        set(case.get("variants", {})) != set(ARMS) or
        any("report" not in variant for variant in case.get("variants", {}).values())
        for case in run["cases"]):
        raise ValueError("Run is incomplete; do not score partial or failed experiments")
    report_map = {}
    for case in run["cases"]:
        for arm, variant in case.get("variants", {}).items():
            if "report" not in variant:
                continue
            key = hashlib.sha256(f"{run['seed']}:{case['case_id']}:{arm}".encode()).hexdigest()[:16]
            report_map[key] = (case["case_id"], arm, variant)
    rows = blind["blind_reports"]
    if not rows:
        raise ValueError("No complete reports to score")
    if {row["report_id"] for row in rows} != set(report_map) or len(rows) != len(report_map):
        raise ValueError("Blind report IDs do not match this run")
    scored = {arm: [] for arm in ARMS}
    agreement = []
    for row in rows:
        case_id, arm, variant = report_map[row["report_id"]]
        if row["case_id"] != case_id or row["report"] != variant["report"]:
            raise ValueError("Blind report content does not match run output")
        annotations = row.get("annotations", [])
        if len(annotations) != 2 or len({a.get("annotator_id") for a in annotations}) != 2:
            raise ValueError(f"Two distinct human annotations required: {row['report_id']}")
        for annotation in annotations:
            labels = annotation.get("labels", {})
            if (not annotation.get("annotator_id") or
                any(type(labels.get(field)) is not int for field in FIELDS) or
                any(labels[field] < 0 for field in FIELDS[:2]) or
                any(labels[field] not in (0, 1, 2) for field in FIELDS[2:]) or
                not isinstance(annotation.get("evidence_notes"), str) or
                not annotation["evidence_notes"].strip()):
                raise ValueError(f"Incomplete/invalid human labels: {row['report_id']}")
        values = {field: statistics.mean(a["labels"][field] for a in annotations)
                  for field in FIELDS}
        scored[arm].append({"case_id": case_id, **values})
        agreement.append({"report_id": row["report_id"],
                          "exact_agreement": all(annotations[0]["labels"][field] ==
                                                 annotations[1]["labels"][field] for field in FIELDS)})
    by_arm = {}
    for arm, arm_rows in scored.items():
        if arm_rows:
            by_arm[arm] = {field: round(statistics.mean(row[field] for row in arm_rows), 3)
                           for field in FIELDS}
    paired = {}
    for arm in ARMS:
        if arm == "rules" or arm not in by_arm:
            continue
        baseline = {row["case_id"]: row for row in scored["rules"]}
        paired[arm] = {field: round(statistics.mean(row[field] - baseline[row["case_id"]][field]
                                                    for row in scored[arm]), 3)
                       for field in FIELDS}
    budget = []
    for case in run["cases"]:
        variants = case.get("variants", {})
        if not all(arm in variants for arm in ("debate", "budget_repeat")):
            continue
        left, right = variants["debate"], variants["budget_repeat"]
        left_tokens = left.get("incremental_usage", {}).get("prompt_tokens")
        right_tokens = right.get("incremental_usage", {}).get("prompt_tokens")
        left_out = left.get("incremental_usage", {}).get("completion_tokens")
        right_out = right.get("incremental_usage", {}).get("completion_tokens")
        totals = ((left_tokens + left_out, right_tokens + right_out)
                  if all(isinstance(n, int) for n in (left_tokens, right_tokens, left_out, right_out))
                  else (None, None))
        ratio = (round(totals[0] / totals[1], 3) if totals[0] is not None and totals[1] else None)
        budget.append({"case_id": case["case_id"], "debate_to_repeat_token_ratio": ratio,
                       "within_20_percent": ratio is not None and 0.8 <= ratio <= 1.2,
                       "same_review_call_count": left.get("review_calls") == right.get("review_calls")})
    return {"status": "human_labeled", "report_count": len(rows),
            "exact_report_agreement_rate": round(sum(item["exact_agreement"] for item in agreement) / len(agreement), 3),
            "mean_labels_by_arm": by_arm, "paired_delta_vs_rules": paired,
            "budget_match": budget,
            "interpretation_limit": "Small synthetic sample; a 20% token match is a diagnostic, not proof of equal compute. Disagreements need adjudication. Shared diagnosis cannot estimate diagnosis benefit of review strategies."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--blind", type=Path)
    parser.add_argument("--metrics-only", action="store_true")
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    if args.metrics_only:
        result = operational_metrics(run)
    else:
        if not args.blind:
            parser.error("--blind is required unless --metrics-only is set")
        result = score(run, json.loads(args.blind.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
