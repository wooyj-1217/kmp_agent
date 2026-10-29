# 프로젝트 진행 상황 대시보드

로컬·읽기 전용·표준 Python 라이브러리만 사용하는 화면이다. 외부 AI/CDN/업로드/자동 제품 실행은 없다. 실행 현황과 전체 작업 이력을 분리한다. 과거 기록의 실행 귀속을 추정하거나 상태 원장을 복제하지 않는다.

## 실행

저장소 루트에서:

```sh
rtk proxy python3 -B -m harness.dashboard --root /absolute/project/root --port 8780
```

`http://127.0.0.1:8780`에서 확인한다. 화면은 5초 간격으로 읽고, 상세를 펼쳤거나 탭이 숨겨진 경우 자동 갱신을 멈춘다. 지금 갱신 버튼은 별도다. 실시간 프로세스 감시/작업 실행/로그 수집기는 아니다. 열린 역할 실행은 진행 기록으로만 표시하며 생존을 보증하지 않는다.

원본 `tasks.yaml`을 직접 읽는다. `Tasks.read()`는 검증 갱신·로그 쓰기를 하므로 호출하지 않는다. 로그·작업의 파일 생성/수정/권한 변경을 하지 않는다. 전체 이력은 해당 root 안에서만 조회하며 실행별 진척·사용량은 명시 연결된 작업과 정확한 역할 실행 ID에 한정한다. 서로 다른 프로젝트 및 PRODUCT/HARNESS_BUILD/HARNESS_IMPROVEMENT의 혼합을 거부한다. 연결 없는 과거 기록은 이력에만 남는다.

## 연결 데이터 — 상태 원장이 아닌 참조 설정

프로젝트 담당자가 `.harness/dashboard-scopes.json`을 등록한다. 자동 생성·소급 귀속은 하지 않는다. 파일이 없거나 실행을 선택하지 않으면 완료 단계·사용량을 합산하지 않는다. 진행 기록이 있는 범위가 하나면 우선 선택하고 여러 개면 선택을 요청한다. 설정 오류 시 오류를 표시하며 이전 화면을 최신으로 취급하지 않는다.

```json
{
  "project_name": "프로젝트 표시명",
  "scopes": [{
    "id": "사용자가 정한 실행 범위 식별자",
    "name": "이번 개발 실행",
    "project_id": "기존 task.project_id와 정확히 일치",
    "work_type": "PRODUCT",
    "goal": "이번에 달성할 목표",
    "scope": "이번 실행에 포함한 것과 경계",
    "tasks": {
      "기존 작업 ID": {"stage": "development", "required": true, "next_action": "다음 행동"}
    },
    "agent_run_ids": ["위 작업에 속한 정확한 기존 역할 실행 ID"],
    "stage_requirements": {
      "development": {"task_ids": ["기존 작업 ID"], "basis": "필수 완료 조건 원본 참조"}
    },
    "approved_baselines": [{
      "label": "개발에 적용하는 승인 기준", "path": "docs/requirements.md",
      "sha256": "실제 승인 파일 해시", "task_ids": ["기존 작업 ID"]
    }],
    "artifacts": [{
      "label": "작성 화면 시안", "kind": "디자인", "approval": "최신 작성본 · 검토 전",
      "path": "docs/prototype.html", "sha256": "등록한 파일 해시"
    }],
    "decisions": [{"status": "OPEN", "requires_human": true,
      "question": "실제 사람의 선택이 필요한 질문", "impact": "영향받는 작업",
      "basis": "해당 질문의 원본 근거"}],
    "outcome": {"status": "BLOCKED", "summary": "종료 보고", "achieved": "달성한 것",
      "unmet": "미충족 기준", "next": "다음 행동"}
  }]
}
```

stage는 planning/design/development/verification/report. 단계 필수 작업 목록·근거가 없으면 완료 여부 확인 불가다. 하나의 작업이 DONE이어도 단계 완료로 승격하지 않는다. 기준별 필수 리뷰 PASS, 스냅샷 무결성, 코드/입력/산출물 변경 여부를 확인한다. 코드 작업의 단계 통과에는 아래 합의·상태 비교 계약도 필요하다. 원본 상태·리뷰·명령은 상세로 숨긴다. 작업 결과 요약은 `result_summary`와 유효한 `summary_basis: {path, sha256}`가 함께 있을 때만 표시한다. 요약/질문/목표의 의미·권한 자체를 AI가 자동 인증하지는 않는다.

`approved_baselines`는 승인 출처를 참조하는 설정이며 해시 일치가 사용자 승인 증명이 아니다. 최신 작성본과 승인본을 별도 artifact로 연결한다. 승인본이 적용되는 작업은 `task_ids`로 명시한다. 현재 파일과 승인 해시 또는 작업의 frozen 입력이 다르면 재검증 필요다. 과거 검토의 의미를 새 목표의 준수로 바꾸지 않는다.

## 합의 이탈·상태 비교·전체 성공의 분리

선택형 `acceptance-contract.json`을 기존 task 입력으로 freeze하면 `project_contract.review_gate`가 추가 계약을 집행한다. 원래 사용자 합의/명시적 기술 판단 위임의 근거와 기대 기술·경계를 연결하고, 명시 합의 변경을 포괄적 위임으로 정당화하는 선언은 거부한다. `EXPLICIT_DELEGATION`은 원래 명시 합의를 바꾸는 권한이 아니다. 에이전트 기술 결정 문서·기능 PASS 자체를 승인 출처로 쓰지 않는다.

화면 비교는 승인 디자인과 screen/state/platform별 기대를 입력에 등록한다. 빈 입력, 내용 있는 입력, 미저장 이탈 확인, 저장 중, 오류, 결과 불확실 복구 등 **해당 제품의 원본에서 요구한 상태**를 전부 등록해야 한다. 보편적인 상태 목록을 제품 필수 조건으로 자동 추가하지 않는다. 보고 근거는 정확한 승인 디자인·계약·제출 산출물과 결합해야 한다. 단순 기능 PASS나 정상 화면 한 장은 상태 비교 PASS를 대신하지 못한다.

게이트는 증거 연결·필드 일치를 검사한다. 기술 사용 여부·사용자 권한의 의미·이미지 내용의 적합성을 자동 판독하지 않는다. 실제 관측과 별도 검토가 필요하다. 미등록 상태를 자동 발견하는 기능은 없다. 과거 작업에는 소급 적용하지 않으며 대시보드는 기존 기능 PASS와 합의/상태 비교 미확인을 별도로 표시한다. 전체 종료 보고가 PASS여도 모든 단계의 유효한 필수 검토가 없으면 전체 완료로 판정하지 않는다.

계약 최소 구조:

```json
{
  "schema_version": 1,
  "agreements": [{
    "id": "AG-UI", "criterion_id": "기존 필수 AC ID", "authority": "USER_DECISION",
    "decision_basis": "원본 요청/승인 참조", "expected": "합의된 기술과 적용 플랫폼",
    "source": {"path": "원문 근거 경로", "sha256": "...", "snapshot": ".harness/artifacts/...", "snapshot_sha256": "..."}
  }],
  "state_comparisons": [{
    "id": "VIS-EXIT", "criterion_id": "기존 필수 AC ID", "screen": "editor",
    "state": "unsaved-exit-confirmation", "platform": "Android", "expected": "승인된 이탈 확인 표현",
    "approved_design": {"path": "승인 시안 경로", "sha256": "...", "snapshot": ".harness/artifacts/...", "snapshot_sha256": "..."}
  }]
}
```

각 필수 리뷰 evidence JSON은 `tested_outputs: {path: sha256}`, `acceptance_contract_sha256`, `acceptance_checks: {체크ID: {result, observations, method, evidence:[artifact]}}`를 포함한다. 상태 비교 항목에는 screen/state/platform/approved_design_sha256도 일치시킨다. method는 AUTOMATED_TEST/AGENT_REVIEW/USER_CONFIRMATION. 원본 관측/캡처를 artifact로 보존하고 입력별 유효성을 새 실행에서 검토한다. 보고가 있어도 실제 관측이 허위인지를 구조 검사만으로 보장하지 않는다.

## 사용량과 보안

선택한 agent_run_id로 연결된 model_usage의 (session_id,response_id)를 중복 제거한다. 서로 다른 보고·귀속 충돌은 제외하고 건수를 표시한다. 일반 입력=전체 입력−캐시 입력, 총합=일반 입력+캐시 입력+출력. 단계/작업/시각에 연결되지 않으면 귀속 불명으로 남긴다. 전체 수집 완전성은 UNKNOWN이다. 범위 밖 사용량을 현재 실행에 넣지 않는다.

가격은 기본값이 없다. 필요할 때 registry의 `pricing`에 모델별 `{usd_per_million:[일반입력,캐시입력,출력], as_of:"YYYY-MM-DD", source:"공식 단가 출처", tier:"적용 조건"}`를 등록한다. 적용 단가가 없는 행은 미확인이다. API 등가 추정은 실제 청구액과 다르다. 계산식과 모델·기준일·단가는 상세에서 확인한다. 서로 다른 실제 결제 경로의 비용을 확정하지 않는다.

127.0.0.1에만 bind, GET만 지원한다. 문서는 registry에 명시한 안전한 상대 경로·제한 확장자·10MB 이하만 제공한다. 숨김 경로/DB/data/logs/build/node_modules/외부 symlink는 제공하지 않는다. HTML/SVG는 sandbox CSP로 실행·외부통신·상위 탐색을 차단한다. 시안은 inline CSS/데이터 자산 기반 미리보기를 지원한다. 외부 CSS·상대 자산이 필요한 시안은 미리보기에서 제한될 수 있으며 원본을 별도 검토해야 한다. 원본 세션 로그/개인 설정/설치 하네스를 정적 서버로 공개하지 않는다. 로컬 사용자에게 허용한 프로젝트 문서만 명시적으로 연결한다.

### 실제 기록 연결 보완

registry의 `provenance.kind=POSTHOC_CONNECTION`은 사후 연결임을 첫 화면에 표시한다. 원래 run_id를 재작성하지 않는다. `group_kind=UNSTARTED_PLAN`은 실행/사용량 없는 후속 계획으로 취급하고 기존 자료를 새 전환 결과물로 표시하지 않는다. 초기 입력 이력은 `related_history`로 별도 연결한다. 원본 project_id 누락을 보충하거나 이력 전체를 실행에 포함하지 않는다.

작업의 표시명·결과·다음 행동·단계 분류는 근거 문서와 연결한다. `compliance_result=NON_COMPLIANT/WEB_UNDECIDED`는 유효한 compliance_basis 파일이 있는 관측/결정 기록만 표시하며 PASS를 생성하지 않는다. 기술적으로는 등록자가 제공한 원문 대조의 표시이지 자동 기술 탐지/승인 인증이 아니다. 범위가 바뀌면 사후 연결을 다시 검토·생성해야 하며 polling이 새 작업을 자동 편입시키지 않는다.

actual 로그의 recorded_at/observed.occurred_at과 누락된 harness 필드를 읽는다. 당시 검토 결과·시점, 근거 스냅샷의 무결성, 입력/제출 파일의 현재 해시 비교는 별도로 제공한다. `/evidence`는 registry의 정확한 task/review/criterion만 조회하고 원본 JSON의 숫자형 시험 결과·범위·리포트 해시를 선별한다. 구형 목록형 observations와 중첩 reports도 읽으며 명령/환경/응답 본문은 반환하지 않는다. 당시 보고·현재 파일 무결성·현재 목표 준수를 구분한다. Markdown/JSON 명세는 안전한 문서 뷰어로 읽으며 등록된 상대 문서만 링크한다.

원본 프로토타입을 HTML/CSS/JS 인라인 파생본으로 만든 경우에 한해 `interactive_preview=true`와 현재 파일 SHA-256의 일치를 요구할 수 있다. 그 경우 iframe·응답 CSP 둘 다 sandbox allow-scripts만 허용한다. allow-same-origin, 외부 네트워크, 폼 전송, 상위 탐색 권한은 주지 않는다. 파일이 변경되면 스크립트 허용을 중단한다. 서버/DB/원본 저장소 쓰기 엔드포인트가 아니며 메모리 기반 디자인 시연이다. 프로토타입 동작 PASS를 실제 제품의 상태 비교 PASS로 삼지 않는다.

## 재현·검증

```sh
rtk proxy python3 -B -m harness.dashboard_fixture --root /tmp/kmp-dashboard-synthetic
rtk proxy python3 -B -m harness.dashboard --root /tmp/kmp-dashboard-synthetic --port 8780
rtk proxy python3 -B -m unittest harness.test_dashboard harness.test_acceptance_contract harness.test_project_contract harness.test_development_gates
```

fixture는 합성 데이터다. 실제 제품 진행률이나 인수 결과가 아니다. 미선택/정상/동시 진행/수정·재검증/사람 판단/차단 종료를 선택해 확인한다. 원본 기록 불변, 범위 격리, 중복·캐시 산술, 누락·단가 미확인, 경로 차단, 기능 PASS의 합의 PASS 대체 거부를 자동 검증한다.

남은 연결 데이터: 과거 run별 목표·범위·정확한 역할 실행 연결, 단계 필수 작업/완료 조건, 승인 권한 원문·승인 시안, 상태/플랫폼별 실제 관측, 응답별 사용량 귀속·요금 조건, 수집 완전성, heartbeat. 화면만으로 복원하지 않는다. 이번 변경은 독립 역할 자동 실행기/전체 성공 자동 판정기/하네스 배포가 아니다.


## 응답 분류와 사용량 범위

usage_analysis는 적용 프로젝트가 명시한 보존 ZIP의 경로/해시 참조다. 원본을 추출·서빙하지 않고 분석의 허용 필드만 읽는다. 선택 실행 멤버십은 여전히 원장/명시 응답 연결만 사용한다. 정확한 응답 키·모델·토큰이 맞는 사후 분류만 단계 라벨로 표시한다. 작업의 단계로 응답 단계를 추정하지 않는다. 기록 없음은 사용0이 아니며 단계와 재작업 차원은 별도다. 광역 비교는 그 출처의 집계 범위로만 설명하고 선택 그래프/전체 수집률의 분모로 삼지 않는다.

문서/설정 범위는 명시 assessment_scope와 현재 근거가 있을 때 원본 required criteria별 증거·입력·제출/선언 파일 일치를 별도로 표시한다. 원본 verdict/validation_status는 보존하며 제품 gate를 그 작업의 필수 조건으로 승계하지 않는다. Git 커밋만 다른 경우와 실제 파일 변경을 구분하되 재실행 없이 새로운 검증 PASS를 만들지 않는다.
