"""Offline coverage for configurable assessment quotas and hard gates."""
from __future__ import annotations

import unittest

from app.services.assessment_blueprint import build_blueprint
from app.services.question_gen import _validate_questions


def _questions(blueprint: dict) -> list[dict]:
    questions = []
    topics = ["网络出口", "权限策略", "日志定位", "成本模型", "数据分区", "加密密钥",
              "作业调度", "连接超时", "存储格式", "内存配置", "表结构变更", "审计记录",
              "并发限制", "数据血缘", "资源配额", "错误重试", "缓存刷新", "版本升级"]
    for (kind, level), amount in blueprint["expected"].items():
        for _ in range(amount):
            index = len(questions) + 1
            item = {"id": f"q{index:02d}", "type": kind, "difficulty": level,
                    "dimension_id": "cap-a" if index % 2 else "cap-b",
                    "question": f"如何理解{topics[index - 1]}？"}
            if kind == "choice":
                item.update(options=["甲", "乙", "丙", "丁"], correct_answer="A")
            else:
                item.update(scoring_rubric=["机制", "条件", "验证"], reference_answer="根据证据解释")
            questions.append(item)
    return questions


class AssessmentBlueprintTests(unittest.TestCase):
    def test_every_preset_has_consistent_validated_quota(self) -> None:
        for count in (6, 9, 12, 18):
            for profile in ("foundation", "balanced", "advanced"):
                with self.subTest(count=count, profile=profile):
                    blueprint = build_blueprint(count, profile)
                    questions = _questions(blueprint)
                    self.assertEqual(len(questions), count)
                    _validate_questions(questions, {"cap-a", "cap-b"}, blueprint=blueprint,
                                        recent_stems=[], required_caps={"cap-a", "cap-b"})
                    questions[0]["difficulty"] = "L0"
                    with self.assertRaisesRegex(ValueError, "难度分布"):
                        _validate_questions(questions, {"cap-a", "cap-b"}, blueprint=blueprint)

    def test_focused_scope_and_recent_repeat_are_rejected(self) -> None:
        blueprint = build_blueprint(6)
        questions = _questions(blueprint)
        with self.assertRaisesRegex(ValueError, "覆盖"):
            _validate_questions(questions, {"cap-a", "cap-b"}, blueprint=blueprint,
                                required_caps={"cap-c"})
        with self.assertRaisesRegex(ValueError, "重复"):
            _validate_questions(questions, {"cap-a", "cap-b"}, blueprint=blueprint,
                                recent_stems=[questions[0]["question"]])

    def test_invalid_blueprint_is_rejected(self) -> None:
        for params in ((7, "balanced", "comprehensive"),
                       (12, "unknown", "comprehensive"),
                       (12, "balanced", "unknown")):
            with self.assertRaises(ValueError):
                build_blueprint(*params)
