"""Explicit offline process trial. Fixture generation is distinct from real LLM execution."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.roles import Roles, CODE
from harness.tasks import logging
from harness.deliverables import change, restore

FOLDER = "docs/examples/role-execution"
WORKER = [sys.executable, str(CODE / "harness/role_example_worker.py")]


def register(roles, suffix, role, inputs, deps=None, planning=None, cr=None):
    tid = f"TASK-ROLE-{suffix}"
    texts = (["목표·범위·REQ/POL/AC와 근거 분류", "정상·예외·화면 기능과 행동 대응", "미결정 영향·차단과 인계 범위"] if role == "planning" else
             ["요구→화면/상태/행동과 명세·시안 일치", "실제 토큰·컴포넌트·대표안·전체 화면", "구조·동작·캡처 검토와 차단 해소"])
    roles.tasks.register("FEAT-ROLE-001", tid, role, f"메모 예제 {role} {suffix}",
        "합성 메모 가설·선택의 로컬 시안 시험. 실제 제품 정책·선정·저장 연동 제외.",
        [{"id": f"ROLE-{suffix}-{n}", "required": True, "text": t} for n, t in enumerate(texts, 1)], inputs,
        dependencies=deps, max_attempts=2, visual_required=role == "design")
    roles.setup(tid, FOLDER, planning, cr)
    return tid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["init", "planning", "review-planning", "design", "review-design", "change", "report"])
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--fixture", action="store_true", help="Offline deterministic worker; never report this as an LLM")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    record = CODE / ".harness/logs/role-trial.json"
    if args.step == "init":
        if record.exists():
            raise ValueError("existing trial preserved; use existing run")
        run = logging.Logger(CODE).start("HARNESS_BUILD", "orchestrator", "기획·디자인 독립 프로세스·버전·브라우저 시험")
        roles = Roles(CODE, run)
        register(roles, "P1", "planning", [FOLDER + "/brief.md", "docs/examples/task-handoff/requirements.md"])
        register(roles, "D1", "design", [FOLDER + "/brief.md"], ["TASK-ROLE-P1"], "P-001")
        Roles.write(record, {"run_id": run, "folder": FOLDER})
    else:
        run = json.loads(record.read_text())["run_id"]
        roles = Roles(CODE, run)
        p, d = f"TASK-ROLE-P{args.revision}", f"TASK-ROLE-D{args.revision}"
        if args.step in {"planning", "design"}:
            result = roles.execute(p if args.step == "planning" else d, args.step, WORKER if args.fixture else None, args.timeout)
            print(json.dumps(result, ensure_ascii=False))
        elif args.step == "review-planning":
            task = roles.tasks.read()["tasks"][p]
            evidence = FOLDER + f"/evidence/planning-r{args.revision}.md"
            review = roles.tasks.begin(p, "verification", review=True)
            roles.tasks.review(p, review["agent_run_id"], [{"criterion_id": c["id"], "result": "PASS", "evidence": evidence} for c in task["criteria"]], "수행 Codex의 제한된 예제 내용 검토; 제품 정책 승인 아님")
            roles.tasks.handoff(p, d)
        elif args.step == "review-design":
            task = roles.tasks.read()["tasks"][d]
            checks = {}
            for name in ("structure", "interaction", "visual"):
                path = FOLDER + f"/evidence/{name}-r{args.revision}.json"
                report = json.loads((CODE / path).read_text())
                checks[name] = {"result": report["result"], "evidence": path, "environment": report["environment"], "coverage": report["coverage"]}
            review = roles.tasks.begin(d, "verification", review=True)
            state = roles.tasks.review(d, review["agent_run_id"], [{"criterion_id": c["id"], "result": "PASS", "evidence": FOLDER + f"/evidence/structure-r{args.revision}.json"} for c in task["criteria"]], "실제 브라우저 확인 근거를 받는 제한된 예제 검토", checks)
            if state == "DONE":
                target = f"TASK-ROLE-DEV{args.revision}"
                roles.tasks.register("FEAT-ROLE-001", target, "development", "개발 인계 수신만 시험", "실제 개발·제품 인계 제외", [{"id": f"DEV-{args.revision}", "required": True, "text": "개발 실행은 NOT_RUN"}], [], [d], execution_scope="input_interpretation_only")
                roles.tasks.handoff(d, target)
                restore(roles.tasks, FOLDER, f"D-{args.revision:03d}")
        elif args.step == "change":
            cr = change(roles.tasks, FOLDER, "가상 저장 완료 문구를 메모가 저장됐어요로 변경", "명시적 변경 재실행 시험; 실제 사용자 정책 변경 아님",
                ["P-001", "D-001"], {"requirements": ["REQ-002", "EX-FEAT-001-AC-002"], "screens": ["SCREEN-001/SAVED"],
                "checks": ["성공 표시", "컴포넌트 일치", "긴 문자열 시각 검토"], "tasks": ["TASK-ROLE-P2", "TASK-ROLE-D2"]}, FOLDER + "/change-request.md")
            register(roles, "P2", "planning", [FOLDER + "/brief.md", FOLDER + "/requirements.md", FOLDER + "/change-request.md"], cr=cr["id"])
            previous_assets = [str(p.relative_to(CODE)) for p in sorted((CODE / FOLDER / "prototype").rglob("*")) if p.is_file() and p.suffix in {".md", ".css", ".js", ".html", ".json", ".svg"}]
            register(roles, "D2", "design", [FOLDER + "/brief.md", FOLDER + "/design.md", FOLDER + "/change-request.md"] + previous_assets,
                     ["TASK-ROLE-P2"], "P-002", cr["id"])
        elif args.step == "report":
            state = roles.tasks.report()
            summary = {"run_id": run, "tasks": {k: {"state": t["state"], "delivery": t.get("delivery"), "usage": t["usage_summary"]} for k, t in state["tasks"].items() if k.startswith("TASK-ROLE-")},
                       "versions": state.get("deliverables", {}).get(FOLDER), "scope": "메모 예제; fixture 프로세스와 실제 모델 실행을 구분, 실제 제품 미확정"}
            Roles.write(CODE / ".harness/logs/role-trial-report.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
