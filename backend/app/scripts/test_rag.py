"""Smoke test for SAGE retrieval without making an external LLM call."""
from __future__ import annotations

import app.agents.planning as planning
from app.schemas.assessment import KnowledgeGap
from app.services.rag import retrieve_resources
from app.services.taxonomy import get_service


class FakeLLM:
    def chat_traced(self, *args, **kwargs):
        return (
            '{"plan_name":"RAG smoke test","overall_assessment":"ok",'
            '"priority_dimensions":[],"weekly_plan":[],"verification":""}',
            1,
        )


def main() -> None:
    results = retrieve_resources(
        query="Glue Job Full GC 导致 S3 Multipart Upload 失败如何排查",
        service_id="glue",
        capability_ids=["glue_runtime"],
    )
    assert results and results[0].document.source_type == "case"

    original_get_llm = planning.get_llm
    planning.get_llm = lambda: FakeLLM()
    try:
        plan, step, sources = planning.run_planning(
            service_name="AWS Glue",
            overall_level="L1",
            capability_scores={"运行时计算引擎调优与故障诊断": 1.0},
            gaps=[KnowledgeGap(
                gap_id="gap_gc",
                capability_id="glue_runtime",
                title="Full GC 导致上传中断",
                misunderstanding="未能定位根因",
                correct_understanding="从 Spark UI 与 GC 日志验证 Full GC",
            )],
            svc=get_service("glue") or {},
        )
    finally:
        planning.get_llm = original_get_llm

    assert plan.plan_name == "RAG smoke test"
    assert step.status == "ok"
    assert sources and sources[0]["source_type"] == "case"
    print(f"RAG smoke test passed: {len(sources)} sources, {sources[0]['document_id']}")


if __name__ == "__main__":
    main()
