"""开放题评分脚本。

模拟 SE 回答开放题，调用 LLM 进行多维度评分。
验证完整链路：题目 -> 作答 -> AI 评分 -> 能力评级。

用法（在项目根目录执行）：
    python scripts/score_answers.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 设置环境
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

from app.services.llm import get_llm


def load_questions() -> list[dict]:
    questions_path = Path(__file__).resolve().parent.parent / "data" / "questions" / "glue_questions.json"
    with open(questions_path, encoding="utf-8") as fp:
        data = json.load(fp)
    return data.get("questions", [])


# 模拟一个中等水平 SE 的回答（故意有对有错、有遗漏）
SIMULATED_ANSWERS = {
    "open_1": """\
从日志来看，S3 Multipart Upload 报了 SocketException: Unexpected end of file from server，
说明上传过程中连接被断开了。我觉得可能是网络问题或者 S3 服务端的问题。

排查思路：
1. 先看是不是网络抖动，检查 VPC 网络配置
2. 看 S3 服务是否有异常（查看 AWS Health Dashboard）
3. 如果是 Spark 作业，可以考虑增加重试次数

建议增加 spark.task.maxFailures 的值，或者加大 worker 数量来分散负载。
""",
    "open_2": """\
VPC 公有子网无法出站是因为 Glue 的 ENI 不分配公有 IP。
解决方案是把 Connection 改为私有子网，然后配一个 NAT 网关。
NAT 网关绑定 EIP，这个 EIP 就是固定出口 IP，可以给对方加白名单。

具体步骤：
1. 创建私有子网
2. 创建 NAT 网关并绑定 EIP
3. 私有子网路由表加 0.0.0.0/0 -> NAT
4. Glue Connection 选这个私有子网
""",
    "open_3": """\
AccessDenied 说明权限不够。需要检查 Glue Job 的 IAM Role 有没有 s3:ListBucket 和 s3:GetObject 权限。

解决方案：
1. 在 IAM 策略中添加对目标 bucket 的 s3:ListBucket 和 s3:GetObject 权限
2. 确认策略已经 attach 到 Glue Job 的 execution role 上

如果加了 IAM 策略还不行，可能是 S3 的 bucket policy 有 explicit deny。
""",
}


SCORING_PROMPT = """\
你是 AWS Glue 方向的资深 SE，正在评估一名初级 SE 的开放题回答。

请从以下 5 个维度评分（每个维度 1~5 分）：
1. **准确性**：技术判断是否正确，是否有错误信息
2. **完整性**：是否覆盖了关键知识点，有无重要遗漏
3. **诊断思路**：排查逻辑是否清晰，是否从正确方向切入
4. **深度**：是否触及根因，还是只停留在表面现象
5. **实操性**：给出的建议是否可执行，是否具体

评分标准：
- 1 分：完全错误或无关
- 2 分：方向大致对但有明显错误
- 3 分：基本正确但有遗漏或不够深入
- 4 分：正确且较完整，有少量可改进空间
- 5 分：专家级回答，准确完整深入

题目信息：
- 题目：{question}
- 评分要点：{rubric}
- 参考答案：{reference}

SE 的回答：
{answer}

请输出严格 JSON：
{{
  "scores": {{
    "accuracy": <1-5>,
    "completeness": <1-5>,
    "diagnostic_approach": <1-5>,
    "depth": <1-5>,
    "practicality": <1-5>
  }},
  "total_score": <5-25>,
  "level": "L1/L2/L3",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1", "不足2"],
  "feedback": "一段针对性的改进建议，50~100字"
}}

level 判定标准：
- L1 (5-12分): 入门级，需要系统学习
- L2 (13-19分): 熟练级，有一定实战经验
- L3 (20-25分): 专家级，深入理解底层原理
"""


def main() -> None:
    questions = load_questions()
    open_questions = [q for q in questions if q["type"] == "open"]

    if not open_questions:
        print("no open questions found")
        return

    print(f"==> 找到 {len(open_questions)} 道开放题，开始评分...\n")

    llm = get_llm()
    results = []

    for i, q in enumerate(open_questions):
        # 匹配模拟答案
        answer_key = f"open_{i + 1}"
        answer = SIMULATED_ANSWERS.get(answer_key)
        if not answer:
            print(f"  跳过第 {i+1} 道（无模拟答案）")
            continue

        print(f"  🔍 评分第 {i+1} 道: {q['question'][:50]}...")

        prompt = SCORING_PROMPT.format(
            question=q["question"],
            rubric=json.dumps(q.get("scoring_rubric", []), ensure_ascii=False),
            reference=q.get("reference_answer", ""),
            answer=answer,
        )

        response = llm.chat(
            [
                {"role": "system", "content": "你是 AWS Glue 资深 SE，严格按 JSON 格式评分。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        # 清理
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            score_data = json.loads(cleaned)
            score_data["question_id"] = q["id"]
            score_data["dimension_id"] = q.get("dimension_id", "")
            score_data["sub_skill_id"] = q.get("sub_skill_id", "")
            results.append(score_data)

            scores = score_data.get("scores", {})
            total = score_data.get("total_score", 0)
            level = score_data.get("level", "?")
            print(f"     总分: {total}/25  级别: {level}")
            print(f"     准确:{scores.get('accuracy',0)} 完整:{scores.get('completeness',0)} "
                  f"思路:{scores.get('diagnostic_approach',0)} 深度:{scores.get('depth',0)} "
                  f"实操:{scores.get('practicality',0)}")
            print(f"     反馈: {score_data.get('feedback', '')[:80]}")
            print()
        except json.JSONDecodeError as e:
            print(f"     ⚠️  评分结果解析失败: {e}")
            print(f"     raw: {cleaned[:200]}")
            print()

    # 保存评分结果
    output_dir = Path(__file__).resolve().parent.parent / "data" / "scores"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "demo_score_result.json"
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump({"answers_scored": results}, fp, ensure_ascii=False, indent=2)

    # 生成能力雷达图数据
    if results:
        print("=" * 50)
        print("📊 能力雷达图数据（基于本次测评）：\n")
        radar_data = {}
        for r in results:
            dim = r.get("dimension_id", "unknown")
            scores = r.get("scores", {})
            avg = sum(scores.values()) / len(scores) if scores else 0
            radar_data[dim] = round(avg, 1)

        for dim_id, score in radar_data.items():
            bar = "█" * int(score) + "░" * (5 - int(score))
            print(f"  {dim_id}: {bar} {score}/5")

        print(f"\n==> 评分结果已保存到: {output_path}")

    # 总结
    if results:
        avg_total = sum(r.get("total_score", 0) for r in results) / len(results)
        levels = [r.get("level", "?") for r in results]
        print(f"\n📋 总体评价：平均分 {avg_total:.1f}/25，能力级别分布: {levels}")


if __name__ == "__main__":
    main()
