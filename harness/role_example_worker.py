"""Deterministic process fixture for the memo example, NOT an LLM agent.

Used to test transport, artifact generation and revision preservation offline.
Real independent model execution uses the default codex adapter in roles.py.
"""
import json
import hashlib
from pathlib import Path
import sys


def produce(packet):
    changed = bool(packet["delivery"].get("change_id"))
    saved = "메모가 저장됐어요" if changed else "저장 완료"
    source = "기존 docs/examples/task-handoff/requirements.md의 미승인 메모 가설을 사용한 HARNESS_BUILD 예제. 실제 제품 선정·사용자 정책 승인이 아니다."
    definition_list = sorted([[d["path"], d["sha256"]] for d in packet["definitions"]])
    bundle = hashlib.sha256(json.dumps(definition_list, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    revision = "-r2" if changed else ""
    names = {v: f"memo-harness-draft-{bundle[:12]}-{v}{revision}.html" for v in ("A", "B")}
    if packet["role"] == "planning":
        text = f"""# 메모 작성 — 실행 예제 요구사항

{source}
공식 작업본: requirements.md. 공식 기준본과 P 번호는 기존 tasks.yaml deliverables의 인계 기록 참조. 이번 버전은 {'P-002 / CR-001' if changed else 'P-001'}.

## 문제·사용자·목표
짧은 생각을 기록하는 사용자가 본문을 작성하고 가상 저장 결과를 확인한다는 가설(INFERRED). 목표는 기획→디자인→검증·명시적 변경 재실행을 검증하는 것(CONFIRMED: 사용자 하네스 구축 요청).

## MVP 범위·제외
포함: 한 작성 화면, 비어 있지 않은 본문 입력, 가상 저장·성공·오류·재시도, 초기 빈 화면 표현. 제외: 실제 영속 저장, 목록·검색, 실제 제품 정책 확정. API가 없는 검토 시안이며 사용자 데이터는 저장하지 않는다.

## 요구사항·정책·수용 기준
| REQ | 요구·정책 | 근거 | 수용 기준 |
| --- | --- | --- | --- |
| REQ-001 | 본문 입력과 동일 문자열 표시 | INFERRED / 기존 메모 예제 | EX-FEAT-001-AC-001: 회의 메모 입력 시 동일 문자열 |
| REQ-002 | 가상 저장 중 중복 요청 차단·성공 결과 표시 | INFERRED / POL-001 | EX-FEAT-001-AC-002: 저장→처리 중→{saved} |
| REQ-003 | 실패 시 본문 유지·오류·재시도 | INFERRED / POL-002 | EX-FEAT-001-AC-003: 실패→본문 유지→재시도→처리 중 |
| REQ-004 | 빈 값 저장·길이·이탈·처리 중 편집 정책 | UNKNOWN / 기존 Q-001~005 | EX-FEAT-001-AC-004: 실제 제품 빈 값 정책 검증 NOT_RUN, 해당 분기 차단 |

## 흐름
```mermaid
flowchart LR
  Empty[빈 작성 화면] --> Edit[본문 입력]
  Edit --> Saving[가상 저장 요청]
  Saving --> Saved[완료 표시]
  Saving --> Error[오류·본문 유지]
  Error --> Saving
```
FLOW-001 정상은 REQ-001/002·AC-001/002, FLOW-002 실패/복구는 REQ-003·AC-003과 연결한다.

## 화면별 기능·행동·예외
| 화면 | 기능·행동 | 상태·예외 | 기준 |
| --- | --- | --- | --- |
| SCREEN-001 작성 | ACT-INPUT 본문 입력, ACT-SAVE 가상 저장 | EMPTY→EDITING→SAVING→SAVED | AC-001/002 |
| SCREEN-001 작성 | ACT-RETRY 재시도 | ERROR: 입력 유지·오류 후 SAVING | AC-003 |
| SCREEN-001 작성 | 빈 값·미저장 이탈·처리 중 편집 | UNKNOWN: 검토 장치가 상태만 시연, 제품 정책은 미구현 | AC-004 |

## 미결정·차단
Q-001 빈 값/공백, Q-002 최대 길이, Q-003 저장 위치·보장, Q-004 미저장 이탈, Q-005 처리 중 편집 정책은 UNKNOWN. 실제 저장/경계·이탈·편집 동작 및 최종 제품 검증을 차단한다. 비어 있지 않은 본문의 가상 시안과 구조·시각 검토는 진행 가능. 추천·대안은 제품 선정 후 기획이 사용자에게 묶어 확인하며 여기서 임의 채택하지 않는다.

## 인계·변경 영향
기획 기준 검토는 위 제한된 예제 범위만 대상으로 한다. 실제 제품 인계는 차단 상태다. 모든 기능이 INFERRED임을 디자인에 전달한다. {'CR-001은 REQ-002/AC-002/SAVED 표시 문구만 변경한다. 영향 화면 SCREEN-001·검증 성공 표시·후속 TASK-ROLE-D2. 입력·오류·재시도 및 토큰/컴포넌트는 유지한다.' if changed else '최초 기준. 변경 요청 없음.'}
"""
        return {"status": "submitted", "files": [{"path": "requirements.md", "content": text}], "summary": "합성 fixture의 제한된 메모 기획 산출물 생성", "questions": [], "completed": ["requirements"]}

    tokens = """:root{--bg:#f3f5f7;--surface:#fff;--text:#172735;--muted:#516371;--accent:#185c4b;--border:#b8c4cd;--error:#9c2639;--space:16px;--radius:12px;--body:16px;--title:30px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:var(--body)/1.6 system-ui,sans-serif}main{max-width:960px;margin:32px auto;padding:24px;display:grid;grid-template-columns:160px minmax(0,1fr);gap:32px}article{min-width:0;padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}h1{font-size:var(--title);line-height:1.25;margin:0 0 16px}h2{font-size:20px;margin:0 0 16px}p{overflow-wrap:anywhere}small,.muted{color:var(--muted)}label{display:block;margin-bottom:8px}textarea{font:inherit;color:var(--text);width:100%;min-height:180px;padding:var(--space);border:1px solid var(--border);border-radius:8px;resize:vertical}button,select{font:inherit;padding:10px 16px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text)}button{cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:white}button:disabled{opacity:.55;cursor:default}:focus-visible{outline:3px solid #9a5700;outline-offset:3px}.actions,.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.controls{padding:16px;border:1px dashed var(--border);margin-top:24px}#feedback{min-height:32px;margin:16px 0}.error{color:var(--error)}.stack{display:grid;gap:16px}.sample{padding:16px;border:1px solid var(--border);border-radius:8px}@media(max-width:600px){main{display:block;margin:0;padding:16px}aside{margin-bottom:16px}article{padding:16px}h1{font-size:26px}}\n"""
    # The same token/component bytes are kept across the explicit copy change.
    components = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>메모 컴포넌트</title><link rel="stylesheet" href="tokens.css"><main><aside>메모 예제</aside><article class="stack"><h1>공통 컴포넌트</h1><section class="sample"><h2>버튼</h2><div class="actions"><button class="primary">저장</button><button disabled>저장 중…</button><button>다시 시도</button></div></section><section class="sample"><h2>본문 입력</h2><label for="sample">메모 본문</label><textarea id="sample">긴 본문도 줄바꿈하며 입력합니다.</textarea></section><section class="sample"><h2>피드백</h2><p>저장 완료</p><p class="error">저장하지 못했어요. 본문은 유지됩니다.</p><p class="muted">아직 작성한 내용이 없어요.</p></section></article></main></html>"""
    # Gallery copy follows the requirement too; component structure and CSS remain stable.
    components = components.replace("저장 완료", saved)
    system = """# 메모 예제 최소 디자인 시스템

기존 저장소를 조사했으며 docs/examples에는 문서 예제만 있고 재사용 가능한 실제 CSS/컴포넌트 파일은 없었다. 제품은 미정이다. 이 예제에서 실제 사용하는 범위만 생성한다.

tokens.css: 배경 --bg, 표면 --surface, 본문 --text, 보조 --muted, 강조 --accent, 테두리 --border, 오류 --error, 간격 --space=16px, 모서리 --radius=12px, 본문 --body=16px, 제목 --title=30px. 모든 화면과 components.html이 같은 파일을 참조한다.

COMP-INPUT은 label+textarea와 포커스 표시, COMP-BUTTON은 primary/disabled/retry, COMP-FEEDBACK은 완료/오류/빈 상태이다. 실제 시각 예제는 components.html. 버튼 색은 상태와 역할을 나타내고 오류에는 텍스트 설명을 함께 제공한다. 모바일 390×844/데스크톱 1280×900에서 패딩과 단일/이중 열을 조절한다. 대표 B는 가운데 단일 열·짧은 헤더, A는 왼쪽 안내·오른쪽 편집 위계다. 비교안은 동일 콘텐츠와 상태를 사용한다.
"""
    def screen(variant):
        layout = '<style>main{max-width:700px;grid-template-columns:1fr}aside{border-bottom:1px solid var(--border);padding-bottom:16px}</style>' if variant == "B" else ""
        return f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>메모 작성 {variant}</title><link rel="stylesheet" href="tokens.css">{layout}
<!-- Example only. Planning {'P-002' if changed else 'P-001'}; design {'D-002' if changed else 'D-001'}/{variant}; harness draft-{bundle}; definition list {json.dumps(definition_list, ensure_ascii=False)}. Explicit change: {'CR-001 saved copy' if changed else 'initial fixture'}. -->
<main data-screen-id="SCREEN-001"><aside><strong>메모 예제</strong><p class="muted">떠오른 생각을<br>가볍게 적어보세요.</p><small>실제 제품 미확정</small></aside><article><h1>생각을 기록하세요</h1><p class="muted">아래 저장 동작은 검토용 가상 시연입니다.</p><label for="body">메모 본문</label><textarea id="body" data-action-id="ACT-INPUT" placeholder="회의 메모를 입력하세요"></textarea><p id="feedback" role="status" aria-live="polite" data-state-id="EMPTY">아직 작성한 내용이 없어요.</p><div class="actions"><button id="save" class="primary" data-action-id="ACT-SAVE">가상 저장</button><button id="retry" data-action-id="ACT-RETRY" hidden>다시 시도</button></div><section class="controls" aria-label="검토 장치"><label for="state">검토 상태</label><select id="state"><option>EMPTY</option><option>EDITING</option><option>SAVING</option><option>SAVED</option><option>ERROR</option></select><label for="result">가상 응답</label><select id="result"><option value="success">성공</option><option value="error">실패</option></select><small>제품 UI가 아닌 검토 장치. 빈 값·처리 중 편집 정책은 UNKNOWN.</small></section></article></main>
<script>
const body=document.getElementById('body'),feedback=document.getElementById('feedback'),save=document.getElementById('save'),retry=document.getElementById('retry'),state=document.getElementById('state'),result=document.getElementById('result');
function render(s){{state.value=s;feedback.dataset.stateId=s;feedback.className=s==='ERROR'?'error':'';feedback.textContent={{EMPTY:'아직 작성한 내용이 없어요.',EDITING:'작성 중',SAVING:'저장 중…',SAVED:{json.dumps(saved, ensure_ascii=False)},ERROR:'저장하지 못했어요. 입력한 본문은 유지됩니다. 다시 시도하세요.'}}[s];save.disabled=s==='SAVING';save.textContent=s==='SAVING'?'저장 중…':'가상 저장';retry.hidden=s!=='ERROR'}}
state.onchange=()=>render(state.value);body.oninput=()=>render(body.value?'EDITING':'EMPTY');
function request(){{if(!body.value.trim()){{feedback.textContent='빈 값 저장 정책은 미정입니다.';return}}render('SAVING');setTimeout(()=>render(result.value==='error'?'ERROR':'SAVED'),700)}}
save.onclick=request;retry.onclick=request;
</script></html>"""
    design = f"""# 메모 작성 디자인 — 실행 예제

{source}
기준 기획: {packet['delivery']['planning_version']}. 디자인 {'D-002' if changed else 'D-001'}. 공식 기준본은 tasks.yaml의 전달 artifacts. 현재 작업본 design.md/prototype/는 승인본과 별개다.

## 대표안과 선택
A: 왼쪽 안내·오른쪽 편집으로 정보 위계를 나눔. B: 가운데 단일 열로 편집 집중, 넓은 화면 활용이 적음. 동일 SCREEN-001·내용·상태·크기로 prototype/{names['A']}, {names['B']} 비교. **A 선택은 시험 시나리오의 합성 결정이며 실제 사용자 선택이 아니다.** fixture brief의 선택 근거를 재사용하며 변경마다 다시 선택하지 않는다. 실제 제품에서 선택 미정이면 checkpoint 대기.

적용 지침은 draft-{bundle}. 경로순 [경로, SHA-256] UTF-8 JSON(공백 없는 구분자, 비ASCII 그대로)의 SHA-256. 목록: `{json.dumps(definition_list, ensure_ascii=False)}`. 실제 기준 HEAD는 context.json 입력의 git_commit을 참조하며 미커밋 지침 사용. 비교안 A/B는 같은 tokens.css를 참조하고 이 시험 CR에서는 CSS bytes를 유지한다. JavaScript는 HTML 내 포함, 외부 의존 없음. 이전 비교안 파일은 유지한다.

## 화면·흐름·목적
SCREEN-001 작성은 이 예제 대상 전체 화면이다. 진입→EMPTY→ACT-INPUT→EDITING→ACT-SAVE→SAVING→SAVED/ERROR→ACT-RETRY→SAVING. 정보 위계는 제목→본문→결과→행동. 검토 장치는 별도 표시. 목록·이탈 화면은 범위 밖이며 실제 탐색/이탈 정책은 UNKNOWN. 웹 직접 진입은 초기 화면, 새로고침은 샘플 초기화이며 영속/미저장 보호는 구현하지 않았다.

| REQ·AC | SCREEN·STATE | ACT·컴포넌트 |
| --- | --- | --- |
| REQ-001 / EX-FEAT-001-AC-001 | SCREEN-001 / EMPTY,EDITING | ACT-INPUT / COMP-INPUT |
| REQ-002 / EX-FEAT-001-AC-002 | SCREEN-001 / SAVING,SAVED | ACT-SAVE / COMP-BUTTON,COMP-FEEDBACK |
| REQ-003 / EX-FEAT-001-AC-003 | SCREEN-001 / ERROR,SAVING | ACT-RETRY / COMP-BUTTON,COMP-FEEDBACK |
| REQ-004 / EX-FEAT-001-AC-004 | 빈 값·실제 경계는 미정 | 제품 동작 NOT_RUN·차단 |

EMPTY는 안내, EDITING은 작성 중, SAVING은 진행·중복 저장 비활성, SAVED는 '{saved}', ERROR는 본문 유지·오류·재시도. textarea 편집 제한은 미채택 정책이며 시안만으로 확정하지 않는다. 키보드 순서는 본문→저장→재시도(표시 시)→검토 상태→가상 응답. 포커스 outline과 aria-live, label을 사용한다. 화면 본문은 세로 스크롤, 가로 넘침 없이 긴 문자열 줄바꿈. 플랫폼은 로컬 HTML 예제이며 실제 제품 플랫폼은 UNKNOWN.

## 실제 자원과 개발 명세
prototype/tokens.css를 화면/컴포넌트가 공유한다. prototype/components.html은 사용하는 상태 예제, prototype/system.md는 토큰·사용 규칙, prototype/index.html은 합성 선택 A의 진입점이다. 로컬 HTTP 또는 파일로 연다. 최소 JS는 가상 응답과 검토 상태만 시연한다. 화면·컴포넌트/토큰 재사용과 세부값은 system.md가 원본이다.

## 검증 계획·남은 문제
화면 SCREEN-001 × EMPTY/EDITING/SAVING/SAVED/ERROR × 1280×900/390×844 및 긴 본문/오류 문구. 구조(소스·실제 DOM/스타일·토큰), 실제 입력·저장·실패·재시도·키보드, 캡처 시각 검토를 별도 보고서로 연결한다. 생성 시 모두 NOT_RUN이며 실제 검토 후 기존 작업 기록으로 판정한다. 스크린샷 위치는 docs/examples/role-execution/evidence/ 및 기존 검토 기록을 참조한다. 명세/시안 불일치·요구 누락·필수 결함이 없을 때만 제한된 예제 인계가 가능하다. 실제 제품 인계는 UNKNOWN 정책으로 차단.

## 변경
{'CR-001: REQ-002/AC-002/SAVED 성공 문구만 갱신. A/B/index와 컴포넌트 예제 문구를 함께 갱신. tokens.css/system.md와 입력·오류·재시도 동작은 유지. 성공 표시 영향 조합을 재검증한다.' if changed else '최초 생성. 실제 검증은 별도 접수 전까지 NOT_RUN.'}
"""
    files = {"design.md": design, "prototype/tokens.css": tokens, "prototype/components.html": components,
             "prototype/system.md": system, "prototype/index.html": screen("A"),
             "prototype/" + names["A"]: screen("A"), "prototype/" + names["B"]: screen("B")}
    return {"status": "submitted", "files": [{"path": p, "content": c} for p, c in files.items()],
            "summary": "합성 fixture의 토큰·컴포넌트·시스템·대표 A/B·전체 단일 화면 생성; 브라우저 검증 NOT_RUN",
            "questions": [], "completed": ["tokens", "components", "prototype"]}


if __name__ == "__main__":
    print(json.dumps(produce(json.load(sys.stdin)), ensure_ascii=False))
