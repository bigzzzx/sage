"""Small, explicit guards for verified factual contradictions in answers."""
from __future__ import annotations

import re


def known_fact_error(question: dict, answer: str) -> str:
    """Return only high-confidence contradictions; never infer missing knowledge."""
    if "classifier_order" in (question.get("source_ids") or []):
        for sentence in re.split(r"[。；;\n]", answer):
            if re.search(r"(?:置信度|certainty).{0,12}(?:大于|超过|>)\s*0(?:\.0)?", sentence, re.I) and re.search(
                r"(?:停止|终止|即止|采用|确认)", sentence
            ):
                return "Glue 分类器并非置信度大于 0 就停止：certainty=1.0 才直接采用，否则继续比较并选最高确定性结果。"
    return ""


def false_g4x_explanation(question: dict) -> bool:
    """A G.4X distractor may be wrong for G.1X, but it is still a real worker."""
    options = question.get("options") or []
    explanation = str(question.get("explanation", ""))
    if not isinstance(options, list):
        return False
    for index, option in enumerate(options[:4]):
        if "16 vCPU" in str(option) and "64 GB" in str(option):
            letter = chr(ord("A") + index)
            if re.search(rf"选项\s*{letter}[^。；;]*不是\s*(?:AWS\s*)?Glue\s*worker", explanation, re.I):
                return True
            if re.search(rf"选项[^。；;]*{letter}[^。；;]*都不是\s*(?:AWS\s*)?Glue\s*worker", explanation, re.I):
                return True
    return False
