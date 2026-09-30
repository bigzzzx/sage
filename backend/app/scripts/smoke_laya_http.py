"""Probe three narrow Chinese decisions against the local Laya HTTP service."""
from __future__ import annotations

import json
from urllib.request import ProxyHandler, Request, build_opener


CASES = [
    ("Crawler会自动清洗CSV并写回S3。", "A"),
    ("Crawler只发现元数据，不会清洗CSV。", "B"),
    ("请先查看Crawler运行日志。", "B"),
]


def main() -> None:
    opener = build_opener(ProxyHandler({}))
    for answer, expected in CASES:
        body = {
            "model": "multilingual",
            "state": answer,
            "questions": {
                "claim": {
                    "type": "choice",
                    "instructions": "只判断文本是否明确声称 Glue Crawler 会清洗 CSV；不要推测真实性。",
                    "criteria": {
                        "A": "文本明确声称 Crawler 会清洗 CSV。",
                        "B": "文本没有声称 Crawler 会清洗 CSV，或明确说它不会清洗。",
                    },
                }
            },
        }
        request = Request(
            "http://127.0.0.1:8011/v1/systemone",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(request, timeout=30) as response:
            result = json.load(response)
        actual = result["answers"]["claim"]["choice"]
        print(json.dumps({"answer": answer, "expected": expected, "actual": actual,
                          "match": actual == expected}, ensure_ascii=False))


if __name__ == "__main__":
    main()
