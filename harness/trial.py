"""Reproducible local document handoff trial; never invokes a model."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location("task_manager", Path(__file__).with_name("tasks.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = "docs/examples/task-handoff"
IDS = {f"EX-FEAT-001-AC-{n:03d}" for n in range(1, 5)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["init", "submit-planning", "review-planning", "start-design", "submit-design", "review-design", "report"])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    tasks = module.Tasks(module.logging.ROOT, args.run_id)
    if args.step == "init":
        tasks.register("FEAT-001", "TASK-001", "planning", "메모 문서 인계 준비", "HARNESS_BUILD 문서 연결; 제품 검증 제외",
                       [{"id": "FEAT-001-AC-001", "required": True, "text": "기획 문서 필수 항목과 메모 수용 기준 4개 유지"},
                        {"id": "FEAT-001-AC-002", "required": True, "text": "UNKNOWN 정책·단계별 차단·후속 담당 보존"}],
                       [BASE + "/brief.md", "docs/examples/memo/requirements.md", "docs/templates/requirements.md", "docs/roles/planning.md"])
        tasks.register("FEAT-001", "TASK-002", "design", "메모 디자인 명세 인계 시험", "문서 명세 작성; 시각 검토 제외",
                       [{"id": "FEAT-001-AC-003", "required": True, "text": "메모 수용 기준 4개를 화면·상태·행동과 연결"},
                        {"id": "FEAT-001-AC-004", "required": True, "text": "명세·시안·시각 검토 상태 분리"}],
                       ["docs/templates/design.md", "docs/roles/design.md"], dependencies=["TASK-001"])
        tasks.ready("TASK-001")
        print(json.dumps(tasks.begin("TASK-001", "planning"), ensure_ascii=False))
        return
    if args.step == "start-design":
        tasks.handoff("TASK-001", "TASK-002")
        print(json.dumps(tasks.begin("TASK-002", "design"), ensure_ascii=False))
        return
    if args.step == "report":
        report = tasks.report()
        tasks.logger.write_metadata("task-trial.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    planning = args.step.endswith("planning")
    task_id = "TASK-001" if planning else "TASK-002"
    document = "requirements.md" if planning else "design.md"
    if args.step.startswith("submit"):
        task = tasks.read()["tasks"][task_id]
        active = next(r for r in task["executions"] if r["kind"] == "work" and r["ended_at"] is None)
        tasks.submit(task_id, active["agent_run_id"], [BASE + "/" + document], "현재 Codex가 역할 지침에 따라 작성한 문서 제출",
                     None if planning else {"specification": "COMPLETE", "mockup": "NOT_PRODUCED", "visual_review": "NOT_RUN"})
        print(json.dumps({"task_id": task_id, "state": "IN_REVIEW"}))
        return
    reviewer = tasks.begin(task_id, "verification", review=True, execution_mode="local_check")
    task = tasks.read()["tasks"][task_id]
    ref = task["outputs"][0]
    text = (tasks.root / ref["snapshot"]).read_text()
    headings = ["목표", "범위", "사용자 흐름", "업무 정책", "시나리오", "수용 기준", "출처", "미결정"] if planning else ["화면", "컴포넌트", "상태", "인터랙션", "토큰", "플랫폼", "시각 자료", "미결정"]
    first = all(h in text for h in headings) and set(re.findall(r"EX-FEAT-001-AC-\d{3}", text)) == IDS
    if planning:
        second = all(q in text for q in ("Q-001", "Q-002", "Q-003", "Q-004", "Q-005", "UNKNOWN", "Mock UI", "실제 저장", "최종 기능 검증", "기획"))
    else:
        mapping = text.split("## 수용 기준 연결", 1)[-1].split("##", 1)[0]
        rows = [line for line in mapping.splitlines() if line.startswith("| EX-FEAT")]
        first = first and len(rows) == 4 and all(all(marker in row for marker in ("SCREEN-", "STATE-", "ACT-")) for row in rows)
        second = all(marker in text for marker in ("명세 작성", "COMPLETE", "시안 제작", "NOT_PRODUCED", "시각 검토", "NOT_RUN"))
    results = [{"criterion_id": c["id"], "result": "PASS" if value else "FAIL", "evidence": BASE + "/" + ("planning-review.md" if planning else "design-review.md")}
               for c, value in zip(task["criteria"], [first, second])]
    evidence = tasks.root / results[0]["evidence"]
    evidence.write_text("# 문서 연결 검토 증거\n\n"
                        + f"- TASK: {task_id}\n- 검토 실행: {reviewer['agent_run_id']}\n- 대상: {ref['path']}\n- 대상 SHA-256: {ref['sha256']}\n"
                        + "- 범위: 로컬 구조 검사. 제품 동작·정책 적합성·시각 검토는 NOT_RUN.\n\n"
                        + "\n".join(f"- {r['criterion_id']}: {r['result']}" for r in results) + "\n")
    state = tasks.review(task_id, reviewer["agent_run_id"], results, "로컬 문서 구조·ID 연결 검사; 의미상 제품 검증이나 시각 검토가 아님")
    print(json.dumps({"task_id": task_id, "state": state, "reviewer_agent_run_id": reviewer["agent_run_id"], "results": results}, ensure_ascii=False))
    if state != "DONE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
