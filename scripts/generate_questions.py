"""题目生成脚本。

基于 case 数据和能力维度地图，调用 LLM 自动生成测评题目（选择题 + 开放题）。
输出到 data/questions/glue_questions.json。

用法（在项目根目录执行）：
    python scripts/generate_questions.py
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


def load_cases() -> list[dict]:
    cases_dir = Path(__file__).resolve().parent.parent / "data" / "cases"
    cases = []
    for f in sorted(cases_dir.glob("glue-*.json")):
        with open(f, encoding="utf-8") as fp:
            cases.append(json.load(fp))
    return cases


def load_taxonomy() -> dict:
    taxonomy_path = Path(__file__).resolve().parent.parent / "data" / "taxonomy" / "glue_taxonomy.json"
    with open(taxonomy_path, encoding="utf-8") as fp:
        return json.load(fp)


def build_context(cases: list[dict], taxonomy: dict) -> str:
    """构建给 LLM 的上下文：case 摘要 + 能力维度概览。"""
    lines = []

    # 能力维度概览
    lines.append("=== 能力维度地图 ===")
    for dim in taxonomy.get("dimensions", []):
        lines.append(f"\n【{dim['name']}】{dim['description']}")
        for sk in dim.get("sub_skills", []):
            lines.append(f"  - {sk['name']}：{sk['description']}")
    lines.append("")

    # Case 摘要
    lines.append("=== 真实 Case 摘要 ===")
    for i, c in enumerate(cases, 1):
        lines.append(f"\nCase {i}: {c['title']}")
        lines.append(f"  摘要: {c['summary']}")
        lines.append(f"  关键技能: {', '.join(c['key_skills'])}")
    lines.append("")

    return "\n".join(lines)


QUESTION_PROMPT = """\
你是 AWS Glue 方向的资深 SE 培训专家。请基于以下能力维度地图和真实 case 摘要，生成一套测评题目。

要求：
1. 生成 5 道选择题（每题 4 个选项，1 个正确答案）+ 3 道开放题
2. 选择题覆盖不同的能力维度，难度从 L1 到 L3 混合
3. 开放题基于真实 case 场景改编，考察诊断思路和解决方案能力
4. 每道题标注对应的能力维度 ID 和子技能 ID
5. 选择题的干扰项要有迷惑性，不能一眼看出错误
6. 开放题要有明确的评分要点（3~5 个得分点）

输出严格 JSON 格式：
{{
  "questions": [
    {{
      "id": "q01",
      "type": "choice",
      "dimension_id": "dim_xx",
      "sub_skill_id": "dim_xx_sk_xx",
      "difficulty": "L1/L2/L3",
      "question": "题目文本",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A",
      "explanation": "答案解析"
    }},
    {{
      "id": "q06",
      "type": "open",
      "dimension_id": "dim_xx",
      "sub_skill_id": "dim_xx_sk_xx",
      "difficulty": "L2/L3",
      "question": "开放题文本（基于真实场景）",
      "scoring_rubric": [
        "得分点1: ...",
        "得分点2: ...",
        "得分点3: ..."
      ],
      "reference_answer": "参考答案要点"
    }}
  ]
}}

{context}

请生成题目（不要包含 markdown 代码块标记）：
"""


def main() -> None:
    cases = load_cases()
    taxonomy = load_taxonomy()

    if not cases:
        print("no cases found")
        return

    print(f"==> 加载了 {len(cases)} 个 case，{len(taxonomy.get('dimensions', []))} 个能力维度")

    context = build_context(cases, taxonomy)
    prompt = QUESTION_PROMPT.format(context=context)

    print("==> 调用 LLM 生成测评题目，请稍候...")
    llm = get_llm()
    result = llm.chat(
        [
            {"role": "system", "content": "你是 AWS Glue 培训专家，输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )

    # 清理可能的 markdown 标记
    cleaned = result.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # 验证 JSON
    try:
        questions = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"warning: LLM output not valid JSON: {e}")
        output_path = Path(__file__).resolve().parent.parent / "data" / "questions"
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "glue_questions_raw.txt").write_text(cleaned, encoding="utf-8")
        print(f"==> raw output saved to: {output_path / 'glue_questions_raw.txt'}")
        return

    # 保存
    output_dir = Path(__file__).resolve().parent.parent / "data" / "questions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "glue_questions.json"
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(questions, fp, ensure_ascii=False, indent=2)

    # 打印摘要
    q_list = questions.get("questions", [])
    choice_count = sum(1 for q in q_list if q["type"] == "choice")
    open_count = sum(1 for q in q_list if q["type"] == "open")

    print(f"\n==> 生成完成! 共 {len(q_list)} 道题（{choice_count} 选择 + {open_count} 开放）\n")

    for q in q_list:
        tag = "📝" if q["type"] == "choice" else "💬"
        diff = q.get("difficulty", "?")
        print(f"  {tag} [{diff}] {q['question'][:60]}...")

    print(f"\n==> 完整结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
