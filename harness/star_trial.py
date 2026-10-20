"""Sequential CR-002 trial using existing roles/tasks. No app implementation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.roles import Roles, CODE
from harness.tasks import logging
from harness.deliverables import change

FOLDER = "docs/examples/role-execution"
P, D, FIX, DEV = "TASK-STAR-P", "TASK-STAR-D", "TASK-STAR-RETURN", "TASK-STAR-DEV"


def register(roles, tid, role, inputs, deps=None, p=None, d=None, cr="CR-002", targets=None):
    criteria = {
        "planning": ["합성 기본값·반전·목록 표시·정렬·동작 예외와 REQ/POL/AC", "목록↔편집 흐름·화면/상태·미정/차단과 변경 영향"],
        "design": ["정확한 기획·토큰·컴포넌트·목록/편집/상태 대응", "실제 브라우저 동작·시각 재검토·차단 문제 해소·공식 검증기록 연결"],
        "development": ["실제 독립 프로세스가 지정 P/D·원본·AC 읽기를 확인", "KMP/Clean Architecture 구현 위치·공통/플랫폼 책임·검증/반환·후속 계획; 앱 빌드 NOT_RUN"]}[role]
    roles.tasks.register("FEAT-ROLE-001", tid, role, "즐겨찾기 연결 시험 " + role,
        "CR-002 합성 예제. 실제 제품 확정·앱 구현·빌드 제외.", [{"id": tid + f"-C{n}", "required": True, "text": t} for n, t in enumerate(criteria, 1)],
        inputs, dependencies=deps, max_attempts=2, visual_required=role == "design")
    roles.setup(tid, FOLDER, p, cr, d, targets)


def fault_worker(packet):
    # Dedicated synthetic candidate; never report this injected fault as model's natural defect.
    inputs = {s["reference"]["path"]: s["content"] for s in packet["inputs"]}
    base = FOLDER + "/"
    index = inputs[base + "prototype/index.html"]
    import re
    main = "app-favorites.html"
    source = "prototype/" + main
    target = "prototype/app-favorites-synthetic-defect.html"
    text = inputs[base + source]
    if not any('ACT-FAV-TOGGLE' in (content or '') for path,content in inputs.items() if path.endswith(('.html','.js'))):
        raise ValueError("fixture requires real favorite controls")
    # Append inside head so no other behavior is changed.
    style = '<style data-synthetic-defect="ISSUE-return-test">[data-action-id="ACT-FAV-TOGGLE"]{display:none!important}</style>'
    text = text.replace('</head>', style + '</head>')
    if style not in text:
        raise ValueError("missing explicit head closure")
    changed = {"prototype/index.html": index.replace(main, "app-favorites-synthetic-defect.html"), target: text,
               "design.md": inputs[base + "design.md"] + "\n\n## 별도 합성 결함 후보\n실제 생성본과 구분한 반환 경로 시험. 앱 토글을 숨긴 후보 prototype/app-favorites-synthetic-defect.html. 웹은 변경 없음. 이전 승인본 보존. 개발 인계 금지·실제 검토 후 반환 예정.\n"}
    reuse = [p[len(base):] for p in inputs if p.startswith(base) and (p.endswith('design.md') or p.startswith(base + 'prototype/')) and p[len(base):] not in changed]
    targets=json.loads(inputs[base+'evidence/star-target-manifest.json'])
    targets['app']['entry']=target
    return {"status": "submitted", "summary": "별도 합성 결함 후보: 앱 즐겨찾기 토글 숨김. 자연 결함 아님; 검토·반환 시험", "files": [{"path": p, "content": c} for p, c in changed.items()], "reuse": reuse, "completed": ["explicit synthetic candidate"], "questions": [], "target_artifacts":targets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["init", "planning", "design", "repair", "development", "defect", "fault-worker", "setup-development"])
    parser.add_argument("--design-version")
    parser.add_argument("--task-id", help="Explicit final design source or correction task")
    args = parser.parse_args()
    if args.phase == "fault-worker":
        print(json.dumps(fault_worker(json.load(sys.stdin)), ensure_ascii=False)); return
    meta = CODE / ".harness/logs/star-trial.json"
    if args.phase == "init":
        if meta.exists():
            raise ValueError("existing trial preserved")
        rid = logging.Logger(CODE).start("HARNESS_IMPROVEMENT", "orchestrator", "CR-002 즐겨찾기 검토 반환·재검증·실제 개발 입력 해석")
        roles = Roles(CODE, rid)
        cr = change(roles.tasks, FOLDER, "즐겨찾기 합성 구조 변경과 검토/수정·실제 개발 입력 해석 연결", "사용자의 하네스 연결 보완 요청",
                    ["P-002", "D-002"], {"requirements": ["favorites default/toggle/list/sort"], "screens": ["SCREEN-LIST", "SCREEN-EDITOR"],
                    "checks": ["favorite state/sort/navigation", "review return/rerender", "development input receipt"], "tasks": [P, D, FIX, DEV]}, FOLDER + "/favorites-request.md")
        register(roles, P, "planning", [FOLDER + "/requirements.md", FOLDER + "/favorites-request.md"], cr=cr["id"])
        assets = [str(p.relative_to(CODE)) for p in sorted((CODE / FOLDER / "prototype").rglob("*")) if p.is_file()]
        register(roles, D, "design", [FOLDER + "/design.md", FOLDER + "/favorites-request.md"] + assets, [P], "P-003")
        Roles.write(meta, {"run_id": rid})
        print(rid); return
    roles = Roles(CODE, json.loads(meta.read_text())["run_id"])
    if args.phase == "defect":
        source=roles.tasks.read()['tasks'][D]
        Roles.write(CODE/FOLDER/'evidence/star-target-manifest.json',source['target_artifacts'])
        assets = [str(p.relative_to(CODE)) for p in sorted((CODE / FOLDER / "prototype").rglob("*")) if p.is_file()]
        register(roles, FIX, "design", [FOLDER + "/design.md", FOLDER + "/favorites-request.md",FOLDER+'/targets-request.md',FOLDER+'/evidence/star-target-manifest.json'] + assets,
                 [P], source['role_contract']['planning_version'],cr=source['role_contract']['change_id'],targets=source['role_contract'].get('design_targets'))
        roles.tasks.handoff(P, FIX)
        print(roles.execute(FIX, "design", [sys.executable, str(CODE / "harness/star_trial.py"), "fault-worker"]))
    elif args.phase == "setup-development":
        if not args.design_version:
            raise ValueError("explicit approved design version required")
        source_id=args.task_id or FIX
        contract=roles.tasks.read()['tasks'][source_id]['role_contract']
        register(roles, DEV, "development", [FOLDER + "/favorites-request.md",FOLDER+'/targets-request.md', "docs/product-architecture.md"], [source_id], contract['planning_version'], args.design_version,
                 cr=contract['change_id'],targets=contract.get('design_targets'))
        roles.tasks.handoff(source_id, DEV)
    else:
        tid, role = {"planning": (P, "planning"), "design": (D, "design"), "repair": (FIX, "design"), "development": (DEV, "development")}[args.phase]
        if args.phase=='repair' and args.task_id:
            tid=args.task_id
        print(roles.execute(tid, role, timeout=300))


if __name__ == "__main__":
    main()
