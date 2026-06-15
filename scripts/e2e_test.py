"""端到端集成测试。

模拟完整用户流程：
1. 加载能力维度 + 题目
2. 模拟 SE 作答（选择题 + 开放题）
3. 选择题自动判分
4. 开放题 AI 评分
5. 汇总能力雷达图
6. 生成个性化学习计划

用法：python scripts/e2e_test.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

from app.services.llm import get_llm

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


# 模拟 SE 的选择题答案（故意答对一些答错一些）
CHOICE_ANSWERS = {
    "q01": "C",  # 可能答错
    "q02": "B",  # 可能答错
    "q03": "B",  # 大概率对
    "q04": "C",  # 可能答错
    "q05": "A",  # 可能答错
}

# 模拟 SE 的开放题答案
OPEN_ANSWERS = {
    "q06": "看日志是 S3 上传失败，可能是网络问题。建议加大重试次数或换用更大的 worker。如果还不行可以联系 AWS 看看 S3 服务端是否有问题。",
    "q07": "公有子网的 Glue ENI 没有公有 IP 所以不能出公网。解决方案是用私有子网 + NAT 网关，NAT 绑 EIP 就是固定出口 IP。",
    "q08": "报 AccessDenied 就是权限不够，需要在 IAM Policy 里加上 s3:ListBucket 和 s3:GetObject。如果是跨账号还需要在 Bucket Policy 里加对应的 Allow。",
}

SCORING_PROMPT = """\
你是 AWS Glue 资深 SE，评估以下回答。

从 5 个维度评分（1~5分）：准确性、完整性、诊断思路、深度、实操性。

题目：{question}
评分要点：{rubric}
参考答案：{reference}
SE回答：{answer}

输出 JSON：
{{"scores":{{"accuracy":<1-5>,"completeness":<1-5>,"diagnostic_approach":<1-5>,"depth":<1-5>,"practicality":<1-5>}},"total_score":<5-25>,"level":"L1/L2/L3","feedback":"50字改进建议"}}
"""

LEARNING_PLAN_PROMPT = """\
你是 AWS Glue 培训专家。根据以下 SE 的测评结果，生成个性化学习计划。

测评结果：
- 总体评级：{overall_level}
- 各维度得分：{dimension_scores}
- 薄弱维度：{weak_dimensions}
- AI 反馈：{feedbacks}

请生成一份 2 周学习计划，包含：
1. 优先学习的维度（最薄弱的 1~2 个）
2. 每个维度推荐 2~3 个学习资源（可以是 AWS 文档链接、KB 文章主题、实操练习）
3. 每天建议投入时间
4. 阶段性验证方式

输出 JSON：
{{
  "plan_name": "针对xxx的2周提升计划",
  "overall_assessment": "一句话总结当前水平",
  "priority_dimensions": ["维度1", "维度2"],
  "weekly_plan": [
    {{
      "week": 1,
      "focus": "本周重点",
      "tasks": [
        {{"day": "1-2", "topic": "主题", "resources": ["资源1"], "time_minutes": 30}},
        {{"day": "3-4", "topic": "主题", "resources": ["资源1"], "time_minutes": 30}},
        {{"day": "5", "topic": "阶段验证", "resources": [], "time_minutes": 20}}
      ]
    }}
  ],
  "verification": "如何验证学习效果"
}}
"""


def main() -> None:
    print("=" * 60)
    print("🚀 SAGE 端到端集成测试")
    print("=" * 60)

    # 1. 加载数据
    taxonomy = load_json(DATA_DIR / "taxonomy" / "glue_taxonomy.json")
    questions_data = load_json(DATA_DIR / "questions" / "glue_questions.json")
    questions = questions_data.get("questions", [])

    choice_qs = [q for q in questions if q["type"] == "choice"]
    open_qs = [q for q in questions if q["type"] == "open"]

    print(f"\n📋 测评开始：{len(choice_qs)} 道选择 + {len(open_qs)} 道开放\n")

    # 2. 选择题判分
    print("--- 选择题判分 ---")
    choice_results = []
    for q in choice_qs:
        user_answer = CHOICE_ANSWERS.get(q["id"], "A")
        correct = q.get("correct_answer", "")
        is_correct = user_answer.upper() == correct.upper()
        choice_results.append({
            "question_id": q["id"],
            "dimension_id": q.get("dimension_id", ""),
            "user_answer": user_answer,
            "correct_answer": correct,
            "is_correct": is_correct,
            "score": 1 if is_correct else 0,
        })
        mark = "✅" if is_correct else "❌"
        print(f"  {mark} {q['id']}: 答{user_answer} 正确{correct} - {q['question'][:40]}...")

    correct_count = sum(1 for r in choice_results if r["is_correct"])
    print(f"\n  选择题得分：{correct_count}/{len(choice_qs)}")

    # 3. 开放题 AI 评分
    print("\n--- 开放题 AI 评分 ---")
    llm = get_llm()
    open_results = []

    for q in open_qs:
        answer = OPEN_ANSWERS.get(q["id"], "不知道")
        print(f"  🔍 评分 {q['id']}...")

        prompt = SCORING_PROMPT.format(
            question=q["question"],
            rubric=json.dumps(q.get("scoring_rubric", []), ensure_ascii=False),
            reference=q.get("reference_answer", ""),
            answer=answer,
        )

        response = llm.chat(
            [{"role": "system", "content": "严格输出 JSON"}, {"role": "user", "content": prompt}],
            temperature=0.2,
        )

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
            open_results.append(score_data)
            print(f"     分数: {score_data.get('total_score', 0)}/25 级别: {score_data.get('level', '?')}")
        except json.JSONDecodeError:
            print(f"     ⚠️ 解析失败，跳过")
            open_results.append({"question_id": q["id"], "total_score": 0, "level": "?", "scores": {}})

    # 4. 汇总雷达图数据
    print("\n--- 📊 能力雷达图 ---")
    dimension_scores = {}

    # 选择题贡献
    for r in choice_results:
        dim = r.get("dimension_id", "unknown")
        if dim not in dimension_scores:
            dimension_scores[dim] = {"correct": 0, "total": 0, "open_scores": []}
        dimension_scores[dim]["total"] += 1
        dimension_scores[dim]["correct"] += r["score"]

    # 开放题贡献
    for r in open_results:
        dim = r.get("dimension_id", "unknown")
        if dim not in dimension_scores:
            dimension_scores[dim] = {"correct": 0, "total": 0, "open_scores": []}
        scores = r.get("scores", {})
        if scores:
            avg = sum(scores.values()) / len(scores)
            dimension_scores[dim]["open_scores"].append(avg)

    # 计算每个维度的综合得分（0~5 分制）
    radar = {}
    for dim, data in dimension_scores.items():
        scores_list = []
        if data["total"] > 0:
            choice_score = (data["correct"] / data["total"]) * 5
            scores_list.append(choice_score)
        for s in data["open_scores"]:
            scores_list.append(s)
        radar[dim] = round(sum(scores_list) / len(scores_list), 1) if scores_list else 0

    # 查找维度名称
    dim_name_map = {}
    for d in taxonomy.get("dimensions", []):
        dim_name_map[d["id"]] = d["name"]

    print()
    for dim_id, score in sorted(radar.items(), key=lambda x: x[1]):
        name = dim_name_map.get(dim_id, dim_id)[:20]
        bar = "█" * int(score) + "░" * (5 - int(score))
        print(f"  {bar} {score}/5  {name}")

    # 5. 识别薄弱维度
    weak_dims = [dim_id for dim_id, score in radar.items() if score < 3.0]
    weak_names = [dim_name_map.get(d, d) for d in weak_dims]

    # 6. 生成学习计划
    print("\n--- 📚 生成个性化学习计划 ---")

    feedbacks = [r.get("feedback", "") for r in open_results if r.get("feedback")]
    overall_avg = sum(radar.values()) / len(radar) if radar else 0
    overall_level = "L1" if overall_avg < 2.5 else ("L2" if overall_avg < 4.0 else "L3")

    plan_prompt = LEARNING_PLAN_PROMPT.format(
        overall_level=overall_level,
        dimension_scores=json.dumps(
            {dim_name_map.get(k, k): v for k, v in radar.items()}, ensure_ascii=False
        ),
        weak_dimensions=json.dumps(weak_names, ensure_ascii=False),
        feedbacks="\n".join(feedbacks),
    )

    plan_response = llm.chat(
        [{"role": "system", "content": "你是培训专家，输出 JSON。"}, {"role": "user", "content": plan_prompt}],
        temperature=0.3,
    )

    cleaned_plan = plan_response.strip()
    if cleaned_plan.startswith("```"):
        lines = cleaned_plan.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_plan = "\n".join(lines)

    try:
        plan = json.loads(cleaned_plan)
        print(f"\n  📌 {plan.get('plan_name', '学习计划')}")
        print(f"  📝 {plan.get('overall_assessment', '')}")
        print(f"  🎯 优先提升: {', '.join(plan.get('priority_dimensions', []))}")
        for week in plan.get("weekly_plan", []):
            print(f"\n  Week {week.get('week', '?')}: {week.get('focus', '')}")
            for task in week.get("tasks", []):
                print(f"    Day {task.get('day', '?')}: {task.get('topic', '')} ({task.get('time_minutes', 0)}min)")
    except json.JSONDecodeError:
        print("  ⚠️ 学习计划 JSON 解析失败")
        plan = {"raw": cleaned_plan}

    # 7. 保存完整测试结果
    output = {
        "test_timestamp": "e2e_demo",
        "choice_results": choice_results,
        "open_results": open_results,
        "radar_data": radar,
        "overall_level": overall_level,
        "weak_dimensions": weak_names,
        "learning_plan": plan,
    }

    output_path = DATA_DIR / "scores" / "e2e_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"✅ 端到端测试完成！完整结果: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
