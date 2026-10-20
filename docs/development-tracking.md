# 개발 작업의 기준·코드·검증 추적

새 개발 버전 번호는 만들지 않는다. 기존 task_id/agent_run_id, artifact/SHA-256, P/D/CR, Git HEAD와 검증 기록을 사용한다. 도구의 VERSION·harness.commit은 도구 릴리스이고, 개발 code_state의 repository_root·head는 대상 프로젝트다. 제품 릴리스 번호·URL 서비스 버전은 Git/계약 해시와 별개다. 제품 릴리스 자동 생성은 지원하지 않는다.

## 설정과 실행

명시 설정이 필요한 경우 기존 작업을 register/configure-stage한 뒤 `tasks.py --root <대상 Git 루트> --run-id <로거 실행> configure-development --data <JSON>`을 호출한다. root는 실제 대상 Git 루트여야 하고 HEAD가 있어야 한다. 도구 저장소를 대상 저장소로 추정하지 않는다. 개발 역할의 기본 실행 범위와 코드 단계(ui/client_integration/server_implementation/integration_verification)는 코드 구현으로 취급한다. register의 execution_scope로 code_implementation/documentation/input_interpretation_only를 명시할 수 있다. 작업 생성 때 target_repository를 대상 Tasks 루트로 기록한다.

ready·begin·인계 수신 시 설정이 없으면 기존 frozen 입력으로 자동 설정한다. P/D 버전이 지정됐으면 해당 버전의 canonical 문서, 그 외에는 유일한 requirements.md/design.md 입력을 사용한다. API·정책은 frozen stage 설정에서만 선택한다. 대상 Git 루트/HEAD, 유일한 기준본, UI/API 적용 단계가 없으면 누락 목록과 configure-development 대안을 안내하고 실행하지 않는다. 현재 문서가 바뀌었어도 과거 snapshot을 자동 교체하지 않는다. 제목·자유문 scope·최신 버전으로 의미나 귀속을 추측하지 않는다.

자동 설정은 전체 대상 Git 저장소를 영향 범위로 보수적으로 추적한다. 새 파일·삭제·HEAD/index·입력 변경도 재검증 대상이며, 근거 파일은 .harness/에 둬 검증 대상 코드와 분리한다. 더 좁은 검증 범위가 필요하면 ready 전에 configure-development의 code_paths를 명시한다. 수동 설정에서 빈 code_paths는 기존대로 영향 미상이며 RECHECK_REQUIRED다.

submit·검증 시작/결과·인계 송신·resume도 공통 게이트를 거친다. 설정이나 시작/제출 증거가 빠진 기존 실행은 사후 자동 설정으로 정당화하지 않고 새 추적 작업을 요구한다. 같은 작업의 추적 범위를 비코드로 낮춰 누락 검사를 우회할 수 없다.

문서 작성은 execution_scope=documentation을 선언하며 Git/코드 추적을 강제하지 않는다. 기존 Roles의 development 진입점은 role_contract.scope=input_interpretation_only이므로 종전 입력 해석·계획 동작을 유지한다. 이러한 면제 작업은 문서 형식만 제출할 수 있으며 소스·설정 파일 제출은 거부한다. 코드 stage와 비코드 선언의 충돌도 거부한다. 기존 제품 구현 worker를 새로 제공하는 기능은 아니다. 과거 검증 근거를 소급 생성하지 않는다.

```json
{
  "task_id": "TASK-CLIENT",
  "baselines": {
    "planning": "docs/requirements.md",
    "design": "docs/design.md",
    "api": "docs/api-contract.md",
    "policy": "docs/policies.md"
  },
  "code_paths": ["src", "tests", "build.gradle.kts"],
  "api_required": true,
  "service_version": "/v1"
}
```

baselines는 해당하는 종류만 지정한다. 선택된 역할 P/D가 있으면 해당 버전의 원본 artifact와 일치해야 한다. API가 필요한 client_integration/server_implementation/integration_verification은 frozen stage 설정의 API·정책과 일치해야 한다. 같은 feature의 API 작업은 ready/begin/review에서 계약·정책 SHA를 비교한다. 기준 전환은 모든 관련 작업을 비활성 TODO/BLOCKED에서 갱신한 뒤 실행한다. 외부 서버만 있는 경우 그 계약을 고정하며 서버 구현 작업 생성을 강제하지 않는다. 서버/API가 없는 UI 작업에는 API를 요구하지 않는다.

API 문서는 요청·응답·오류·인증·정책의 원본 산출물이다. 내용의 의미·완전성은 검토자가 확인한다. 계약 해시는 의미상 호환성 판정이나 서비스 URL 버전이 아니다.

code_paths에는 구현뿐 아니라 동작에 영향을 주는 공유 코드·빌드/의존 설정·검증 코드를 포함한다. 빈 목록은 영향 미상으로 전체 저장소를 관측하고 검증을 RECHECK_REQUIRED로 처리한다. 제출 파일은 지정 범위 안이어야 한다. Git 추적 파일·미추적 비제외 파일·삭제·index·파일 모드를 식별한다. Git 제외 파일은 입력 artifact로 명시하지 않는 한 코드 식별 범위 밖이다. 심볼릭 링크·submodule 범위는 인증하지 않고 거부한다.

## 코드와 검증 근거

begin/submit/review에 HEAD, dirty, 관련 파일 SHA, HEAD 대비 변경, index, 코드 상태 해시를 기록한다. COMMITTED/WORKING_TREE와 제출 바이트가 HEAD에 포함되는지는 별도로 기록한다. dirty 상태에서 HEAD만으로 재현 가능하다고 주장하지 않는다. 자동 commit/tag/push는 없다.

검증 시작 run의 code_state_start와 baseline을 근거 JSON에 연결한다. 검증 동안 코드가 바뀌거나 제출 출력이 바뀌면 접수를 거부한다. PASS 근거에는 아래 필드가 필요하며, 통합 검증의 기존 필수 필드도 계속 적용된다.

```json
{
  "code_state_sha256": "<검증 시작 코드 상태 해시>",
  "baseline": {"references": {}, "inputs": [], "role_contract": null, "stage_contract": null},
  "observations": "<실제 실행·관측 근거>"
}
```

baseline 값은 검증 실행에 저장된 객체 전체를 그대로 참조한다. 구조 일치는 실제 테스트 실행의 증명이 아니므로 검토자가 관측·환경·명령 결과를 확인한다.

작업 명령·show·refresh-validation 시 코드/입력/계약과 과거 검증 기준을 비교한다. 변경·조회 실패·영향 미상이면 기존 validation_status의 review 실행 키를 RECHECK_REQUIRED로 표시한다. 과거 PASS·근거·출력은 변경하지 않고 코드 원복만으로 CURRENT를 회복하지 않는다. 재검증은 새 작업/실행과 새 근거로 남긴다. 최신 검증이 재검증 필요이면 handoff를 거부한다. 상시 파일 감시기는 없으므로 외부 수정 직후에는 refresh-validation으로 명시 점검한다.

## CR과 기준 갱신

기존 deliverables.change에 before_baselines/after_baselines를 전달하면 개발 변경 근거를 추가한다. 기준은 종류별 artifact 객체 또는 대상 상대 경로다. 이전 기준은 현재 작업본 경로 대신 기존 frozen artifact 객체를 사용해야 한다. 기존 before(P/D ID), impacts(requirements/screens/checks/tasks), reason, evidence를 유지한다.

추가 입력은 intervention_ids(기존 linked/pending 이벤트 ID), compatibility(COMPATIBLE/BREAKING/UNKNOWN/NOT_APPLICABLE), compatibility_basis, service_version이다. 개입이 없는 변경은 빈 intervention_ids로 선언한다. 영향 작업은 기존 ID 또는 UNKNOWN이다. UNKNOWN은 현재 작업 전체를 보수적으로 재검증 처리한다. checks에는 영향 기준 ID 또는 UNKNOWN을 명시한다. 호환성·근거 누락은 거부하고 SHA 차이로 호환성을 자동 판정하지 않는다. 이전/새 기준은 보존되며 해당 작업 검증은 재검증 필요로 표시한다.

기준 갱신 configure-development에는 change_id를 지정한다. CR의 before/after와 해당 작업의 기준이 맞아야 하며 영향 작업에 포함돼야 한다. 기존 역할 rebase/configure-stage도 필요한 경우 먼저 갱신한다. 과거 실행의 입력·코드·검토는 유지한다. 서로 다른 기능에서 같은 CR 번호가 있으면 모호한 연결을 거부한다.

## checkpoint의 보장 범위

checkpoint는 실행 상태·질문·결정·보관 문서로 같은 실행을 재개하는 기능이다. checkpoint_capabilities.code_restore=false와 code_restore_supported=false를 기록한다. 코드/index/미추적 바이트의 복원은 보장하지 않는다. Git reset·작업본 덮어쓰기·전체 코드 복구는 제공하지 않는다.

## 확인 범위

`python3 -B -m unittest harness.test_development_tracking harness.test_development_gates`는 임시 Git 대상에서 실제 commit·파일 수정·코드 실행으로 확인한다. 사용자 저장소의 commit/tag/push나 demo-app 구현은 수행하지 않는다. API 내용은 시험 계약이며 실제 서비스 호환성·제품 API 연동 검증은 아니다.
