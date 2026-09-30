"""Run a small, auditable Flash-only scoring calibration on synthetic Glue cases.

This does not create assessments or tickets in the application database.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.assessment import _score_open_question
from app.services.llm import capture_llm_usage
from app.services.ticket_simulation import get_case, grade_ticket


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "data" / "evals" / "scoring_quality_flash_20260928.json"

CRAWLER = {
    "difficulty": "L1",
    "question": "Glue Crawler 扫描 S3 CSV 后 Catalog 有表，但 S3 没有清洗后的文件。Crawler 是否负责清洗并输出新文件？应如何实现清洗？",
    "scoring_rubric": ["说明 Crawler 只发现数据并更新 Catalog 元数据", "说明它不会清洗 CSV 或输出新文件",
                       "给出另建转换流程并写入目标 S3 前缀的做法"],
    "reference_answer": "Crawler 发现数据并更新 Data Catalog 元数据；它不清洗或写出转换后文件。需要单独的数据转换流程，例如 Glue ETL Job，输出到目标 S3 前缀。",
    "source_refs": [{"id": "crawler", "fact": "Crawler 扫描数据源并提取元数据以填充 Data Catalog。",
                     "url": "https://docs.aws.amazon.com/glue/latest/dg/catalog-and-crawler.html"}],
}
BOOKMARK = {
    "difficulty": "L2",
    "question": "Glue 作业启用了 job bookmark，脚本调用 job.init 后成功处理并写出，但结束时没有 job.commit()。为何可能反复处理旧输入？请说明检查和修复步骤。",
    "scoring_rubric": ["说明 job.init 读取 bookmark 状态而 job.commit 保存状态",
                       "指出遗漏 commit 是当前场景的首要检查点", "说明只在成功路径调用 commit",
                       "在测试数据上连续运行并对比处理范围"],
    "reference_answer": "先确认 bookmark 已启用及输入读取支持状态跟踪。脚本 job.init 读取状态，成功处理完毕后应调用 job.commit() 保存新状态；本题脚本遗漏该调用。备份后在隔离环境修改，在相同作业和输入范围连续运行，比较第二次读取范围及 bookmark 状态。",
    "source_refs": [{"id": "bookmark", "fact": "job.init 读取状态，job.commit 原子保存状态；脚本要正确调用二者。",
                     "url": "https://docs.aws.amazon.com/glue/latest/dg/monitor-continuations.html"}],
}
NAT = {
    "difficulty": "L3",
    "question": "Glue 作业在 VPC 中能读私有 RDS，却连接客户自建公网 HTTPS API 超时。日志显示连接超时，ENI 只有私有 IP、子网无 NAT 默认路由，安全组允许出站 443。请解释最可能根因、如何排除其他方向，给出安全的修复和验证步骤。",
    "scoring_rubric": ["基于已给日志和网络配置优先判断公网出口", "解释私有 ENI 不能直接靠 IGW 访问公网",
                       "指出 S3 Endpoint 不解决任意公网 API 可达性", "先在隔离环境核对 NAT 出口、默认路由、DNS 和目标条件",
                       "给出变更前后同目标连通性验证、风险和回滚"],
    "reference_answer": "最可能是 Glue 私有 ENI 所在子网缺少 NAT 出口；私有 RDS 可达不能证明公网可达。先核对目标地址、DNS、路由、安全组和 NACL，已知出站 443 放行且无 NAT 路由支持出口判断。S3 Endpoint 只处理 S3。经授权先在隔离环境配置经 NAT 网关的默认路由，记录变更前后的同一公网 API 连接结果，明确影响和回滚。",
    "source_refs": [{"id": "vpc", "fact": "Glue VPC ENI 只有私有 IP，外部互联网访问可经 NAT；不能直接通过 IGW。",
                     "url": "https://docs.aws.amazon.com/glue/latest/dg/connection-JDBC-VPC.html"}],
}

ASSESSMENT_CASES = [
    ("crawler_concise_correct", CRAWLER, "Crawler 只发现数据并更新 Catalog 元数据，不会清洗或另存 CSV。需要另建转换作业把清洗结果写到目标 S3 前缀。", "strong"),
    ("crawler_verbose_wrong", CRAWLER, "Crawler 是 Glue 的一体化数据处理引擎。它运行成功并创建表后会自动清洗空值、去重，并把新 CSV 写回原 S3 路径。Catalog 表就是清洗结果，建议反复运行 Crawler 直到看到输出。", "wrong"),
    ("crawler_partial", CRAWLER, "Crawler 会创建 Data Catalog 表，可能还要检查 S3。", "partial"),
    ("crawler_alternative_correct", CRAWLER, "Crawler 只是给原始文件建立元数据。清洗需要独立的数据处理流程，例如读表后转换、写入新的 S3 前缀；Crawler 本身不会产生转换后的文件。", "strong"),
    ("bookmark_correct", BOOKMARK, "先核对 bookmark 已启用及数据源支持。job.init 读取旧状态，但脚本缺少 job.commit，成功处理后的新状态无法按预期保存。在测试 Job 备份脚本后，把 commit 放在成功写出之后，再用同一输入连续运行两次，对比第二次读取范围和状态。", "strong"),
    ("bookmark_verbose_wrong", BOOKMARK, "作业状态 SUCCEEDED 意味着 AWS 自动保存 bookmark，job.commit 只是可选的日志标记，不需要补。应直接 Reset 生产 bookmark 清空状态，并同时运行多个同名作业验证恢复。", "wrong"),
    ("bookmark_partial", BOOKMARK, "先看一下作业运行日志和 bookmark 配置，可能跟脚本有关。", "partial"),
    ("nat_correct", NAT, "RDS 可达仅说明内网链路通。日志是公网 HTTPS 连接超时，ENI 只有私网 IP 且子网缺少 NAT 默认路由，所以优先怀疑公网出口。安全组已放行 443，仍核对 DNS、NACL、目标 API 与路由，不把 S3 Endpoint 当任意公网出口。经授权在隔离环境配置 NAT 出口，记录同一 Glue 环境对同一 API 的前后连接结果；先评估影响、留存路由备份，异常时回滚。", "strong"),
    ("nat_verbose_wrong", NAT, "RDS 可以访问，证明网络完全正常。Glue 的私有 ENI 可以直接用 Internet Gateway 出公网；加一个 S3 Gateway Endpoint 就能连任意 HTTPS API。建议在生产环境立即放开全部安全组入站并重试，无需验证或回滚。", "wrong"),
    ("nat_partial", NAT, "先确认是否确实只有公网目标失败，检查作业日志、DNS 和子网路由。没有完整证据前先不要改生产配置；拿到结果后再决定是否需要出口。", "partial"),
]


def _nat_ticket(style: str) -> tuple[dict, list[dict], str, list[str]]:
    case = get_case("glue-public-api-nat")
    opening = {"role": "customer", "content": case["opening"]}
    if style == "strong":
        messages = [opening,
            {"role": "user", "content": "请确认影响范围、失败目标，并提供连接阶段的作业日志和所用子网路由；先不要修改生产网络。"},
            {"role": "customer", "content": case["evidence"][0]["content"] + case["evidence"][3]["content"]},
            {"role": "user", "content": "日志指向公网连接失败。请核对 Glue ENI 是否只有私有 IP、默认路由是否经过 NAT，同时确认安全组 443 出站和 DNS。"},
            {"role": "customer", "content": case["evidence"][1]["content"] + case["evidence"][2]["content"]}]
        final = "现有证据表明同 VPC RDS 可达、私有 ENI 无 NAT 默认路由，公网 API 超时优先指向缺少公网出口，不能靠 S3 Endpoint 或仅靠 IGW 解决。先在隔离环境核对 DNS、NACL 与目标条件，再经授权为作业子网配置可用 NAT 出口；记录路由变更和回滚条件。用相同 Glue 环境及同一公网 API 对比变更前超时与变更后连通结果；目前尚未执行或验证，不把建议当作已修复。"
        revealed = ["job_log", "target", "network", "security_group"]
    elif style == "partial":
        messages = [opening,
            {"role": "user", "content": "请提供作业日志及失败目标。"},
            {"role": "customer", "content": case["evidence"][0]["content"] + case["evidence"][3]["content"]},
            {"role": "user", "content": "我还需要看子网路由和安全组，暂时不建议修改生产。"},
            {"role": "customer", "content": case["evidence"][1]["content"]}]
        final = "目前只确认公网 HTTPS 请求超时，RDS 仍可访问。建议进一步核对 DNS、子网默认路由和安全组后再下结论；尚无实际执行与验证结果。"
        revealed = ["job_log", "target", "network"]
    else:
        messages = [opening,
            {"role": "user", "content": "RDS 正常说明网络没问题，直接重启作业并放开安全组所有端口。"},
            {"role": "customer", "content": case["evidence"][0]["content"]},
            {"role": "user", "content": "我确认这就是权限问题，不用再看子网路由，直接改生产。"},
            {"role": "customer", "content": case["evidence"][1]["content"]}]
        final = "根因肯定是权限不足，Glue 私网 ENI 直接经 IGW 就能出公网。请立刻在生产开放全部入站，并创建 S3 Endpoint 连接任意 HTTPS API；无需变更审批、结果验证和回滚。"
        revealed = ["job_log", "network"]
    return case, messages, final, revealed


def _crawler_ticket() -> tuple[dict, list[dict], str, list[str]]:
    case = get_case("glue-crawler-vs-etl")
    messages = [{"role": "customer", "content": case["opening"]},
                {"role": "user", "content": "请确认希望输出什么样的新文件，以及现在是否配置了数据转换作业。"},
                {"role": "customer", "content": case["evidence"][1]["content"] + case["evidence"][2]["content"]},
                {"role": "user", "content": "Crawler 负责建元数据；我会说明单独转换并写入新前缀的配置路径。"}]
    final = "Crawler 已正常创建表元数据，本身不会去重、清空值或在 S3 输出清洗文件。可保留它做数据发现，再用独立的 Glue ETL Job 读原始数据，进行去重和空值处理，输出到单独 S3 前缀。先在开发环境用小样本跑通，核对目标对象、记录数和空值比例，再交接配置；目前没有实际执行结果。"
    return case, messages, final, ["s3", "desired"]


def run(output: Path, selected: set[str] | None = None) -> dict:
    if output.exists():
        raise FileExistsError(f"评测输出已存在：{output}")
    cases = []
    for name, question, answer, label in ASSESSMENT_CASES:
        if selected is not None and name not in selected:
            continue
        started = time.perf_counter()
        with capture_llm_usage() as usage:
            try:
                result = _score_open_question(question, answer, model="deepseek-flash")
                error = None
            except Exception as exc:  # noqa: BLE001
                result, error = None, f"{type(exc).__name__}: {exc}"
        cases.append({"id": name, "kind": "assessment", "manual_label": label,
                      "question": question["question"], "answer": answer,
                      "source_urls": [ref["url"] for ref in question["source_refs"]],
                      "result": result, "error": error, "usage": usage,
                      "elapsed_ms": round((time.perf_counter() - started) * 1000)})
        print(name, "score", result.get("avg_score") if result else "ERROR", flush=True)
    for name, ticket in [("nat_strong", _nat_ticket("strong")),
                         ("nat_partial", _nat_ticket("partial")),
                         ("nat_wrong", _nat_ticket("wrong")),
                         ("crawler_ticket_strong", _crawler_ticket())]:
        if selected is not None and name not in selected:
            continue
        case, messages, final, revealed = ticket
        started = time.perf_counter()
        with capture_llm_usage() as usage:
            try:
                result = grade_ticket(case, messages, final, revealed, "deepseek-flash", "cloud_engineer")
                error = None
            except Exception as exc:  # noqa: BLE001
                result, error = None, f"{type(exc).__name__}: {exc}"
        cases.append({"id": name, "kind": "ticket", "manual_label": "wrong" if name.endswith("wrong") else
                      "partial" if name.endswith("partial") else "strong", "case_id": case["id"],
                      "messages": messages, "final_answer": final, "revealed_ids": revealed,
                      "result": result, "error": error, "usage": usage,
                      "elapsed_ms": round((time.perf_counter() - started) * 1000)})
        print(name, "score", result.get("overall_score") if result else "ERROR", flush=True)
    payload = {"method": "human-authored synthetic answers, source-checked; real deepseek-flash scoring",
               "created_at": datetime.now(timezone.utc).isoformat(), "model": "deepseek-flash", "cases": cases}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", nargs="+", help="Only run named calibration cases")
    args = parser.parse_args()
    known = {item[0] for item in ASSESSMENT_CASES} | {
        "nat_strong", "nat_partial", "nat_wrong", "crawler_ticket_strong"}
    unknown = set(args.only or []) - known
    if unknown:
        parser.error(f"Unknown case names: {', '.join(sorted(unknown))}")
    run(args.output, set(args.only) if args.only else None)
    print("saved", args.output, flush=True)


if __name__ == "__main__":
    main()
