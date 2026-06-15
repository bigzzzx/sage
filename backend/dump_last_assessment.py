"""一次性查看最近一次测评的完整内容（题目+答案+评分）。"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "sage.db"
c = sqlite3.connect(DB)
row = c.execute(
    """SELECT id, kind, overall_level, choice_score, overall_avg,
              questions_snapshot, answers, question_results, radar, learning_plan, created_at
       FROM assessments ORDER BY created_at DESC LIMIT 1"""
).fetchone()
if not row:
    print("no records")
    raise SystemExit

(aid, kind, level, choice, avg, qs_json, ans_json, qres_json,
 radar_json, plan_json, created) = row

questions = json.loads(qs_json) if qs_json else []
answers = {a["question_id"]: a["answer"] for a in json.loads(ans_json or "[]")}
qresults = {r["question_id"]: r for r in json.loads(qres_json or "[]")}
radar = json.loads(radar_json or "[]")

print(f"========== 测评 {aid}  ({kind})  ==========")
print(f"创建时间: {created}")
print(f"总体评级: {level}    选择题: {choice}    平均分: {avg}/5")
print()

for i, q in enumerate(questions, 1):
    qid = q["id"]
    qtype = q["type"]
    diff = q.get("difficulty", "?")
    dim = q.get("dimension_id", "?")
    print(f"────── Q{i} [{qtype} · {diff}]  维度: {dim} ──────")
    print(f"题目: {q['question']}")

    if qtype == "choice":
        for j, opt in enumerate(q.get("options", [])):
            letter = chr(65 + j)
            mark = ""
            if letter == q.get("correct_answer", ""):
                mark += " ✅"
            if letter == answers.get(qid, ""):
                mark += " 👈我选的"
            print(f"  {letter}. {opt}{mark}")
        r = qresults.get(qid, {})
        print(f"\n>>> 你的答案: {answers.get(qid, '(未答)')}    {'✅ 正确' if r.get('is_correct') else '❌ 错误'}")
        if q.get("explanation"):
            print(f">>> 解析: {q['explanation']}")
    else:
        print(f"\n>>> 你的回答:")
        print(answers.get(qid, "(未答)"))
        r = qresults.get(qid, {})
        sd = r.get("score_detail") or {}
        print(f"\n>>> 评分: 总分 {r.get('total_score', 0)}/25  级别 {r.get('level', '-')}")
        if sd:
            print(f"     准确性 {sd.get('accuracy', 0)}/5  完整性 {sd.get('completeness', 0)}/5  "
                  f"诊断思路 {sd.get('diagnostic_approach', 0)}/5  深度 {sd.get('depth', 0)}/5  实操性 {sd.get('practicality', 0)}/5")
        if r.get("feedback"):
            print(f">>> 反馈: {r['feedback']}")
        if q.get("scoring_rubric"):
            print(f">>> 评分要点:")
            for p in q["scoring_rubric"]:
                print(f"     - {p}")
    print()

print("========== 雷达图 ==========")
for r in radar:
    bar = "█" * int(r["score"]) + "░" * (5 - int(r["score"]))
    print(f"  {bar} {r['score']}/5  {r['dimension_name']}")
