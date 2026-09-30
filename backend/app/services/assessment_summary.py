"""Evidence-aware, question-weighted assessment summary."""
from __future__ import annotations

from collections import Counter


def _level_for_score(score: float) -> str:
    return "L1" if score < 2.5 else ("L2" if score < 4 else "L3")


def summarize_answers(questions: list[dict], results: list[dict]) -> dict:
    """Use every scored answer; never let one capability hide errors elsewhere."""
    by_id = {item.get("question_id"): item for item in results}
    values: list[float] = []
    coverage: Counter[str] = Counter()
    difficulty_scores: dict[str, list[float]] = {"L1": [], "L2": [], "L3": []}
    open_scores: dict[str, list[float]] = {"L1": [], "L2": [], "L3": []}
    critical_error = False
    for question in questions:
        result = by_id.get(question.get("id"))
        if not result:
            continue
        raw = float(result.get("total_score") or 0)
        value = max(0.0, min(5.0, raw if question.get("type") == "choice" else raw / 5))
        values.append(value)
        difficulty = str(question.get("difficulty", "")).upper()
        if difficulty in difficulty_scores:
            difficulty_scores[difficulty].append(value)
            if question.get("type") == "open":
                open_scores[difficulty].append(value)
                detail = result.get("score_detail") or {}
                if isinstance(detail, dict) and (0 < float(detail.get("accuracy") or 0) <= 2
                                                 or (difficulty == "L3" and 0 < float(
                                                     detail.get("root_cause_identification") or 0) <= 2)):
                    critical_error = True
        coverage[str(question.get("dimension_id", ""))] += 1
    average = round(sum(values) / len(values), 2) if values else 0.0
    level = _level_for_score(average)
    level_reason = ""
    advanced = difficulty_scores["L2"] + difficulty_scores["L3"]
    advanced_open = open_scores["L2"] + open_scores["L3"]
    if level == "L3" and (len(difficulty_scores["L3"]) < 2 or not open_scores["L3"]
                          or sum(difficulty_scores["L3"]) / len(difficulty_scores["L3"]) < 4
                          or max(open_scores["L3"]) < 4 or critical_error):
        level = "L2"
        level_reason = "L3 场景题或开放题证据不足，暂不评为 L3"
    if level == "L2" and (len(advanced) < 2 or not advanced_open
                          or sum(advanced) / len(advanced) < 2.5
                          or max(advanced_open) < 2.5):
        level = "L1"
        level_reason = "L2 及以上场景题或开放题证据不足，暂不评为 L2"
    rated_dimensions = sum(count >= 2 for count in coverage.values())
    reliable = (len(values) >= 12 and rated_dimensions >= 3
                and len(advanced) >= 2 and bool(advanced_open)
                and len(difficulty_scores["L3"]) >= 2 and bool(open_scores["L3"]))
    missing = []
    if len(values) < 12:
        missing.append("少于 12 题")
    if rated_dimensions < 3:
        missing.append("有充分题目覆盖的能力点少于 3 个")
    if len(advanced) < 2 or not advanced_open:
        missing.append("L2 及以上场景题覆盖不足")
    if len(difficulty_scores["L3"]) < 2 or not open_scores["L3"]:
        missing.append("L3 场景题或开放题覆盖不足")
    return {"overall_avg": average, "overall_level": level,
            "rating_reliable": reliable, "question_count": len(values),
            "rated_dimensions": rated_dimensions,
            "rating_reason": ("、".join(missing) + "，暂不定级" if not reliable else
                              "存在关键技术判断失误，高级等级暂不授予" if critical_error and average >= 4 else
                              level_reason),
            "difficulty_coverage": {key: len(value) for key, value in difficulty_scores.items()}}
