"""能力维度建模脚本。

读取 data/cases/*.json，调用 LLM 提炼 Glue 能力维度地图。
输出到 data/taxonomy/glue_taxonomy.json。

用法（在项目根目录执行）：
    python scripts/build_taxonomy.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 把 backend 加入 path 以复用 LLM 客户端
import os
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, backend_dir)
# 确保 .env 能被加载（pydantic-settings 从 cwd 读 .env）
os.chdir(backend_dir)

from app.services.llm import get_llm


def load_cases() -> list[dict]:
    """加载 data/cases 目录下所有 case JSON（排除模板）。"""
    cases_dir = Path(__file__).resolve().parent.parent / "data" / "cases"
    cases = []
    for f in sorted(cases_dir.glob("glue-*.json")):
        with open(f, encoding="utf-8") as fp:
            cases.append(json.load(fp))
    return cases


def build_case_summaries(cases: list[dict]) -> str:
    """把 case 列表压缩成 LLM 能看的摘要文本。"""
    lines = []
    for i, c in enumerate(cases, 1):
        lines.append(f"--- Case {i}: {c['title']} ---")
        lines.append(f"Tags: {', '.join(c['tags'])}")
        lines.append(f"Summary: {c['summary']}")
        lines.append(f"Key Skills: {', '.join(c['key_skills'])}")
        lines.append("")
    return "\n".join(lines)


TAXONOMY_PROMPT = """\
你是 AWS Glue 方向的资深技术经理，正在为 SE 团队设计能力评估体系。

下面是 {n} 个真实的 Glue 支持案例摘要。请基于这些案例，结合你对 AWS Glue 服务全貌的理解，输出一份 **Glue SE 能力维度地图**。

要求：
1. 提炼 5~8 个一级能力维度（Dimension），每个维度下列出 2~5 个二级子技能（Sub-skill）
2. 每个维度和子技能都附带简短描述（一句话）
3. 每个子技能标注对应的熟练度分级标准（L1 入门 / L2 熟练 / L3 专家），用一句话描述每个级别
4. 维度划分要有区分度：不同维度之间覆盖不同的知识领域，避免重叠
5. 不要局限于这 5 个 case，基于你对 Glue 全貌的理解补充合理的维度

输出严格 JSON 格式，schema 如下：
{{
  "service": "Glue",
  "version": "1.0",
  "dimensions": [
    {{
      "id": "dim_01",
      "name": "维度名称",
      "description": "一句话描述",
      "sub_skills": [
        {{
          "id": "dim_01_sk_01",
          "name": "子技能名称",
          "description": "一句话描述",
          "levels": {{
            "L1": "入门级描述",
            "L2": "熟练级描述",
            "L3": "专家级描述"
          }}
        }}
      ]
    }}
  ]
}}

以下是 case 摘要：

{case_summaries}

请输出 JSON（不要包含 markdown 代码块标记）：
"""


def main() -> None:
    cases = load_cases()
    if not cases:
        print("❌ 没有找到 case 文件，请先在 data/cases/ 中添加 case。")
        return

    print(f"==> 加载了 {len(cases)} 个 case")
    summaries = build_case_summaries(cases)

    prompt = TAXONOMY_PROMPT.format(n=len(cases), case_summaries=summaries)

    print("==> 调用 LLM 生成能力维度地图，请稍候...")
    llm = get_llm()
    result = llm.chat(
        [
            {"role": "system", "content": "你是 AWS Glue 方向的资深技术专家，输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    # 尝试清理可能的 markdown 代码块标记
    cleaned = result.strip()
    if cleaned.startswith("```"):
        # 去掉首行 ```json 和末尾 ```
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # 验证是合法 JSON
    try:
        taxonomy = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"⚠️  LLM 输出不是合法 JSON，保存原始文本。错误: {e}")
        output_path = Path(__file__).resolve().parent.parent / "data" / "taxonomy" / "glue_taxonomy_raw.txt"
        output_path.write_text(cleaned, encoding="utf-8")
        print(f"==> 原始输出已保存到: {output_path}")
        return

    # 保存
    output_path = Path(__file__).resolve().parent.parent / "data" / "taxonomy" / "glue_taxonomy.json"
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(taxonomy, fp, ensure_ascii=False, indent=2)

    # 打印摘要
    dims = taxonomy.get("dimensions", [])
    print(f"\n==> 生成完成 ✅  共 {len(dims)} 个能力维度：\n")
    for d in dims:
        skills = d.get("sub_skills", [])
        print(f"  📌 {d['name']}（{len(skills)} 个子技能）")
        for sk in skills:
            print(f"      - {sk['name']}")
    print(f"\n==> 完整结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
