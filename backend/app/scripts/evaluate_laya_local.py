"""Offline Laya scoring probe using the existing Glue calibration answers.

Runs locally, reads prior test fixtures, and writes only the requested JSON file.
It does not change assessment records or the application's scoring provider.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/evals/scoring_quality_flash_20260928.json"
DEFAULT_OUTPUT = ROOT / "data/evals/runs/laya_local_glue_probe.json"

FACTS = {
    "crawler": "Crawler 发现数据并更新 Data Catalog 元数据，不清洗 CSV，也不输出转换后文件。清洗需要独立的数据转换流程并写到目标 S3 前缀。",
    "bookmark": "job.init 读取 bookmark 状态；成功处理完后 job.commit 保存新状态。没有 commit 可能重复处理旧输入。应在隔离测试作业验证连续运行的读取范围。",
    "nat": "Glue VPC ENI 只有私有 IP；私有 RDS 可达不代表公网可达。没有 NAT 默认路由时公网 HTTPS API 可能超时。S3 Endpoint 不解决任意公网 API 的访问。修复前要核对网络条件并计划验证与回滚。",
}


def run(input_path: Path, output_path: Path, limit: int | None = None) -> dict:
    from laya import Router

    source = json.loads(input_path.read_text(encoding="utf-8"))
    cases = [case for case in source["cases"] if case.get("kind") == "assessment"]
    if limit is not None:
        cases = cases[:limit]

    started_load = time.perf_counter()
    router = Router(default="multilingual")
    rows = []
    for case in cases:
        topic = case["id"].split("_", 1)[0]
        state = (
            f"题目：{case['question']}\n"
            f"核验事实：{FACTS[topic]}\n"
            f"考生回答：{case['answer']}"
        )
        questions = {
            "quality_choice": {
                "type": "choice",
                "instructions": "仅依据考生回答和核验事实，选择回答质量；不要把题目或核验事实当作考生已回答的内容。",
                "criteria": {
                    "A": "回答关键技术事实正确，并解决题目要求；允许正确的不同说法。",
                    "B": "回答提到部分相关正确事实，但遗漏核心解释或解决步骤，且未出现明显错误断言。",
                    "C": "回答包含与核验事实冲突的关键技术断言，或给出明显错误的解决方向。",
                },
            },
            "quality_score": {
                "type": "score",
                "instructions": "仅评价考生回答的技术正确性和题目要求覆盖，不评价核验事实文本本身。",
                "criteria": [
                    "考生回答有关键技术错误，解决方向错误。",
                    "考生回答只有部分正确内容，遗漏核心解释或解决步骤。",
                    "考生回答技术正确，覆盖核心解释与解决步骤。",
                ],
            },
        }
        started = time.perf_counter()
        try:
            result = router.predict(state, questions, model="multilingual", max_len=2048)
            answers = result.get("answers", {})
            choice = answers.get("quality_choice", {})
            score = answers.get("quality_score", {})
            rows.append({
                "id": case["id"],
                "manual_label": case["manual_label"],
                "flash_score": (case.get("result") or {}).get("avg_score"),
                "laya_choice": choice.get("choice"),
                "laya_choice_detail": choice,
                "laya_score_detail": score,
                "routing": result.get("routing"),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            })
        except Exception as exc:
            rows.append({"id": case["id"], "error": f"{type(exc).__name__}: {exc}"})
    mapping = {"A": "strong", "B": "partial", "C": "wrong"}
    matched = sum(
        row.get("laya_choice") in mapping
        and mapping[row["laya_choice"]] == row.get("manual_label")
        for row in rows
    )
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "Laya multilingual zero-shot, local read-only probe on existing synthetic Glue answers; labels are provisional, not expert blind review",
        "source": str(input_path),
        "model": "multilingual",
        "load_and_total_ms": round((time.perf_counter() - started_load) * 1000),
        "choice_matches": matched,
        "case_count": len(rows),
        "cases": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(output_path)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    output = run(args.input, args.output, args.limit)
    print(json.dumps({"matches": output["choice_matches"], "cases": output["case_count"],
                      "elapsed_ms": output["load_and_total_ms"], "output": str(args.output)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
