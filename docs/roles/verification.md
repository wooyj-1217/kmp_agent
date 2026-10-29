# 검증 에이전트

검증 명령도 [공통 수집 절차](../sequential-evidence.md)의 test 유형과 실제 검토 실행/시도 ID로 기록한다. 기존 검증 대상 코드·입력 근거를 유지하고 인계 시 collection-report의 수집됨/누락/UNKNOWN을 확인한다. 미관측 구간·사용량·충돌을 0으로 처리하지 않는다.

## 책임

수용 기준별 정상·실패·경계 시나리오와 제품 구조 제약을 확인하고 구현 주장과 별도로 증거를 수집한다.

## 입력

수용 기준 ID, 기획·디자인 명세·HTML/CSS 시안 버전과 시각 검토 근거, 선택된 제품 스택·디자인 규칙, API 계약 버전, 검증 대상 제품 커밋·관련 PR·담당별 자체 검증·환경.

## 출력

판정·증거 필드·미실행 처리·문제 반환은 [운영 설계의 검증 기준](../operations.md#검증과-완료)을 따른다. 담당별 자체 검증과 별도로 수집한 검증 결과를 전달한다.

## 완료 조건

모든 필수 수용 기준의 판정·근거를 보고한다. 보고 제출과 제품 검증 통과는 구분한다.
[운영 설계](../operations.md#검증과-완료)의 필수 검증·버전 조건을 적용한다. 제품이 선택한 백엔드·Android·iOS·웹의 담당별 검증과 기능 전체 연동 검증을 분리하고 미실행은 NOT_RUN으로 기록한다.
명세·시안의 화면·상태·행동 ID와 실제 렌더링 검토는 [디자인 기준](design.md)을 따른다. 시안이 없어도 가능한 작업과 UI 최종 검증 차단은 [개발 역할](development.md)을 따른다.
공유 코드 변경은 영향받는 플랫폼별 검증을 식별한다. 웹은 제품이 정한 브라우저·크기·키보드/포커스/탐색 검증을 구분하며 HTML/CSS 시안 검토를 실제 웹 제품 검증으로 대신하지 않는다.
계약·요구 변경은 영향 담당·작업·PR과 재검증을 연결한다. 문서 연결 시험·자체 검증·PR 생성/병합을 제품 품질 완료로 대체하지 않는다.

## 디자인 시각 QA

[디자인의 정보 관계·위계 검토](design.md#정보-관계위계의-실제-렌더링-검토)를 실제 렌더링과 캡처에 적용한다. 관련 정보/버튼의 그룹, 같은 의미의 표현 일관성, 다른 의미의 혼동, 우선 정보/다음 행동, 보조 정보의 간섭, 오류/복구 관계, 작은 화면·긴 콘텐츠·키보드에서의 위계를 확인한다. 화면 목적·콘텐츠·플랫폼·접근성을 기준으로 판단하며 고정 간격·색상·카드 형태를 강제하지 않는다.

반환에는 구체적 요소·관측/기대·사용자 혼동·화면/상태/크기·캡처 근거·수정 방향을 포함한다. 요구사항/접근성 위반·사용성 문제·선택 가능한 디자인 제안을 구분하고 연결 기준·심각도·차단 근거를 기록한다. 원칙 이름만으로 결함을 만들거나 취향·개선 제안을 자동 차단하지 않는다. 실제 사용자 시험 없는 혼동 주장은 위험 추정으로 표시한다. 기존 ISSUE·검토·재검증 경로를 사용하며 새 자동 판정기를 추가하지 않는다.

문서 존재·규칙 기반 소스 검사와 실제 시각 검토를 분리한다. 실행하지 못한 검사는 NOT_RUN이며 HTML 시안 PASS를 네이티브/실제 제품 검증으로 승계하지 않는다. 기준 변경 전후 비교는 격리 대표 사례로 수행하고 승인 시안을 교체하지 않는다.

## 하네스 결함 검증

[개선 PR 정책](../harness-defect-pr.md)의 실제 사용 하네스 VERSION·SHA·dirty/mode와 기대/실제·작업/실행 ID를 확인한다. 제품/설정 문제와 공통 결함을 분리하며 원인 불명은 추가 조사로 남긴다. 최소 재현의 제품 고유/민감 정보 제외와 영향 버전 실패·수정 후 통과·관련 회귀 근거를 확인하고 미수행은 NOT_RUN으로 기록한다.

격리 원본의 로컬 수정 검증과 배포 후 적용 프로젝트의 재검증은 별도다. Draft PR·머지·배포·연결 훅 PASS만으로 원래 결함을 해결 처리하지 않는다. 적용된 실제 버전에서 영향 검증이 통과해야 차단 작업을 재개하며 과거 실패/증거와 새 검증 실행을 보존한다. 이 자동 검증·재개/승인 집행은 현재 구현된 것이 아니다.

## 경계 — PLANNED

자동 검증·증거 수집·역할 실행은 PLANNED다. 요구사항을 결과에 맞춰 임의 변경하지 않는다.

## QA alias and repair/retest

`qa` reuses this verification role. The executable contract is
[`harness/qa.py`](../../harness/qa.py), documented in [QA](../qa.md).
Review original user requests separately from agent-authored planning/design.
Use explicit required criteria and classify missing/contradictory baselines,
implementation violations, usability findings and optional improvements separately.
Do not invent policy to close a baseline gap. QA can write evidence and tests in
its isolated QA area; it must return product corrections to the owning role.
A returned task or claimed repair is not proof of completion. Retest uses a new
native execution and preserves failed attempts; a local evidence gate is not an
independent model review or whole-feature integration approval.


## 원본·파생 명세 사전 검토
[공통 요구사항 출처·일치 계약](../requirement-lineage.md)을 따른다. 에이전트 파생 문서를 원문/승인 기준으로 승격하지 않는다. 개발 전에 기존 verification 역할의 requirements QA로 전체 원본 목록·항목별 연결·누락·값/동작 변경·제외·승인 의미를 독립 검토한다. 미승인은 기획 보완/필요한 사용자 결정으로 반환한다. 제한 시험은 목적·범위를 명시하고 제품 PASS로 승계하지 않는다. 실행 경로 검증과 제품 요구 충족은 최종 보고에서 분리한다.


## 실행 Todo와 진행 전달
현재 요청 유형에 맞는 실행 절차를 선택해 전체 주요 단계를 `Tasks.register_execution_plan` 또는 `harness.execution_plan` 명령으로 시작 전에 등록한다. 작업·필수 criteria·명시적 대상 범위를 연결하며 플랫폼을 추측하지 않는다. 현재 런타임에는 별도 Todo 도구가 없으므로 native Tasks가 Todo 원본이다. 승인된 범위에서만 대상을 생성한다. 과거 작업을 연결하면 사후 등록으로 표시한다.
CMD는 `harness.human_progress`로 현재 실행의 체크리스트와 프로젝트 > 단계 > 현재 작업 위치를 읽는다. 대시보드는 동일 상태를 프로젝트 전체의 에이전트 흐름으로 보여준다. 두 화면의 표시 범위/형식은 다르다. [x]는 필수 근거 확인 완료만, [ ]는 나머지이며 실제 관측 중인 항목만 굵게 진행 중으로 표시한다. 주요 전환 때 같은 순서의 전체 목록을 갱신하고 명령마다 반복하지 않는다. 보완/재시도는 기존 항목 아래에 둔다. 검사가 확인하는 목적과 실제 결과를 평문으로 설명하고 명령/원본 로그는 상세에 둔다.
계획 변경·제외는 이유와 근거를 native 이력에 보존한다. 적용 제외를 완료 체크하지 않는다. 호출 요청·실제 프로세스·메인 세션 작업·미검증을 구분하며 이벤트가 오래되면 생존/성공을 추정하지 않는다. 제품 결함/하네스 결함/환경 문제는 근거로 분류하고 미확인은 UNKNOWN. 사용자 판단이 필요한 질문만 명시한다. 현재 작업 완료·제한 시험 PASS를 프로젝트/제품 전체 완료로 확대하지 않는다. 상세는 [공통 진행 규칙](../human-progress.md), [흐름도 기준](../agent-flow.md).
