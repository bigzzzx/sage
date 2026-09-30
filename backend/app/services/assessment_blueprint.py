"""Deterministic assessment quotas shared by generation and validation."""
from __future__ import annotations

from collections import Counter

QUESTION_COUNTS = {6: (4, 2), 9: (6, 3), 12: (8, 4), 18: (12, 6)}
DIFFICULTY_WEIGHTS = {
    "foundation": (6, 3, 1),
    "balanced": (1, 1, 1),
    "advanced": (1, 4, 5),
}
FOCUS_LABELS = {
    "comprehensive": "综合能力",
    "configuration": "配置与权限",
    "troubleshooting": "日志与故障排查",
    "architecture": "架构、性能与成本",
}


def _allocate(count: int, weights: tuple[int, int, int]) -> tuple[int, int, int]:
    raw = [count * weight / sum(weights) for weight in weights]
    result = [int(value) for value in raw]
    for index in sorted(range(3), key=lambda i: (raw[i] - result[i], weights[i], -i), reverse=True)[:count - sum(result)]:
        result[index] += 1
    return tuple(result)


def build_blueprint(question_count: int = 9, difficulty_profile: str = "balanced",
                    focus: str = "comprehensive") -> dict:
    if question_count not in QUESTION_COUNTS:
        raise ValueError("题量仅支持 6、9、12 或 18 题")
    if difficulty_profile not in DIFFICULTY_WEIGHTS:
        raise ValueError("未知难度方向")
    if focus not in FOCUS_LABELS:
        raise ValueError("未知出题侧重点")
    choice, open_ = QUESTION_COUNTS[question_count]
    weights = DIFFICULTY_WEIGHTS[difficulty_profile]
    choice_levels = _allocate(choice, weights)
    open_levels = _allocate(open_, weights)
    expected = Counter()
    for kind, amounts in (("choice", choice_levels), ("open", open_levels)):
        for level, amount in zip(("L1", "L2", "L3"), amounts):
            if amount:
                expected[(kind, level)] = amount
    return {
        "question_count": question_count,
        "num_choice": choice,
        "num_open": open_,
        "difficulty_profile": difficulty_profile,
        "focus": focus,
        "expected": expected,
    }
