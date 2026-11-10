# 구조화 계약 foreground 오케스트레이터

`python3 -m harness.orchestrator`는 등록된 feature의 기획 → 기획 검토 → 디자인 → 디자인 검토 → 개발계획 → 개발계획 검토 → 구현 → 독립 QA를 한 foreground 호출 안에서 선택·실행한다. 자연어 목표 분해, task 생성 추론, 무인 background 재시작 서비스는 제공하지 않는다. 프로세스 종료 후에는 명시적 `resume`이 필요하다.

## 사전 조건과 실행

기존 Tasks API로 세 stage task, criteria, dependencies, stage workflow와 Roles.setup을 등록한다. 개발계획 산출물은 기존 `development-execution` fenced JSON 계약을 사용한다. 실행 정책이 적용된 작업은 기존 native session binding, 전체 실행계획 membership 및 상세 work plan이 필요하다. 초기 세 stage의 계획은 사전 등록하고, 나중에 생성될 구현·자식·QA·보완 작업의 계획은 계약의 `work_plans`에 task ID별 기존 계획 객체로 명시할 수 있다. 컨트롤러는 이 명시 객체만 기존 configure_task_plan에 연결한다. 이 컨트롤러는 기준·권한 정책·상세 계획을 대신 작성하거나 완화하지 않는다.

```json
{
  "version": 1,
  "stages": {
    "planning": {"task_id": "PLAN"},
    "design": {"task_id": "DESIGN"},
    "development_plan": {"task_id": "DEVPLAN"}
  },
  "reviewer": {"timeout": 300},
  "qa": {
    "task_id": "QA", "stage": "implementation",
    "original_requests": ["inputs/request.md"],
    "criteria": [{"id": "AUTH", "description": "요구된 인증 동작 검증", "required": true}],
    "commands": [], "max_attempts": 2, "timeout": 600
  },
  "completion": "qa"
}
```

```sh
python3 -m harness.orchestrator --root . --run-id RUN --feature-id FEATURE configure --contract inputs/execution.json
python3 -m harness.orchestrator --root . --run-id RUN --feature-id FEATURE run
python3 -m harness.orchestrator --root . --run-id RUN --feature-id FEATURE status
python3 -m harness.orchestrator --root . --run-id RUN --feature-id FEATURE resume
```

같은 run binding으로 실행한다. 다른 run으로 전환하거나 승인된 계약·범위를 바꾸려면 새 검토된 계약을 등록해야 하며 이 버전은 기존 계약의 인라인 교체를 지원하지 않는다. configure는 같은 파일 해시·run의 재등록만 허용한다.

`worker`(각 stage argv), `reviewer.command`(argv), QA `executable`은 합성 테스트·명시적 adapter용 선택 항목이다. 기본 모델 실행은 기존 Codex 실행기를 사용한다. custom reviewer에는 마지막 argv로 packet JSON 경로를 전달하며 stdout으로 `{summary, results, evidence_documents?, design_checks?}` JSON을 반환한다. `evidence_documents`의 안전한 파일명→내용을 adapter가 execution UUID 경로에 저장하고 `@파일명` 참조를 실제 증거 경로로 바꾼다. 결과 PASS는 독립 프로세스의 판단이며 controller가 생성하지 않는다. 디자인의 실제 구조/상호작용/시각 증거 계약은 기존 Tasks.review가 검사한다. 합성 PNG·합성 reviewer 성공을 실제 시각 검증으로 해석해서는 안 된다.

## 검증 범위

0.4.0 준비 시점의 실제 모델 기획→디자인→개발→QA 전체 E2E는 **NOT_RUN**이다. 기존 검증은 합성 worker·reviewer를 사용하는 subprocess 통합·계약 회귀 범위이며, 실제 제품 산출물·시각 품질의 실증이 아니다. 기본 Codex 실행기 연결 구현과 실제 모델 전체 완주 기록을 구분한다. 버전별 실행 근거는 [0.4.0 지원 현황](releases/v0.4.0.md)을 참조한다.

## 권한·상태 계약

- `CONTINUE`: 현재 호출 안에서 다음 action을 선택할 수 있다.
- `WAITING_FOR_APPROVAL`: 계약/단계에 필요한 typed 인간 승인 근거가 없다.
- `WAITING_FOR_INPUT`: 필수 질문 응답이 없다.
- `RECHECK_REQUIRED`: 입력·검토 기준·코드·증거·정책이 현재 승인 기준과 다르다.
- `RECOVERABLE`: 명시적인 소유권 확인·복구가 필요하다. 이름만으로 사망 또는 안전한 재개를 보장하지 않는다.
- `BLOCKED`: 안전성 불명, 실패한 검토/실행, 소진된 한도, 유효한 보호 인증 부재 등이다.
- `COMPLETED`: 선택한 계약의 범위만 충족했다. `completion_scope`를 함께 읽는다.

PRODUCT는 실제 `execution_policy`가 PRODUCT에 적용되고 현재 native binding이 존재해야 한다. 계약의 `approval_question_id` 및 세 stage workflow의 `human_approval_question_id`가 필수다. 정책 파일의 이름이나 `role=human`, 일반 PASS로 승인하지 않는다. 계약 승인 receipt는 기존 native HUMAN_APPROVAL 경로에서 purpose=`orchestration`, task=기획 task, subject=`{feature_id, contract_sha256}`, artifacts=계약 파일 및 source_artifacts 전체 현재 해시와 정확히 일치해야 한다. 단계 승인은 기존 `stage:<stage>` purpose와 readiness subject/artifacts를 따른다. 질문 생성·사용자에게 실제 승인 수집은 기존 Decisions CLI/API를 사용한다. 대기 결과에 question ID를 반환하며 승인/응답 후 다시 `run`한다.

원장 `orchestrations[feature_id]`에 frozen 계약 artifact, 기존 역할·검토 계약, 원본 입력, 정책·binding, action/attempt/stop 증거를 추가한다. 기존 task state·schema를 대체하지 않는다. 프로젝트 내부 adapter 파일은 bytes hash를 pin한다. 프로젝트 밖 실행파일/모델 서비스와 같은 OS 계정의 원장·코드 변경에 대한 운영 보안 격리는 별도 과제다.

## 실행·복구·완료 경계

단계 산출물은 Roles, 일반 검토는 별도 managed reviewer process, 다음 단계 가능 여부는 stage_readiness, 구현은 implementation_bridge→요구사항 계보의 독립 비교 QA→Development, QA와 허용된 보완은 Roles→QA/qa_repair가 담당한다. 완료된 단계도 현재 입력·출력·증거를 재검사한다. 검토 기준을 바꾸어 실패를 PASS로 만드는 경로는 제공하지 않는다.

feature별 TaskLease는 같은 feature의 컨트롤러 중복 실행을 막고, 각 하위 실행은 3차 task lease·process guardian·통합 journal을 유지한다. 중단된 실행은 일반 `run`이 재시도하지 않는다. `resume`이 기존 recover_tasks/resume_task를 호출하며, 실제 소유권 불명·변경된 baseline·수동 개입 recovery는 차단한다. 일반 실행 실패 또는 검토 실패는 자동 완화하지 않는다. 계약의 `retry_failed_tasks`가 명시한 task ID만 기존 retry budget 안에서 재시도한다. 기존 task repair/decision/recovery 경로로 해결한 후 재호출한다. QA 보완 루프는 계약의 repair_task_id와 기존 한도·권한을 따른다. review 중단의 자동 재개는 기존 recovery가 지원하는 범위만 가능하다.

`completion=qa`의 COMPLETED는 `QA_OBSERVATION_ONLY`다. 인간 승인·공식 인증을 추론하지 않는다. `completion=official`은 현재 보호 발행자 증거 PASS와 OFFICIAL_CERTIFICATION 및 기존 공식 review 게이트가 필요하다. 일반 QA PASS, ROLE_REVIEW, 인간 승인, LEGACY_UNCERTIFIED DONE은 공식 인증을 대신할 수 없다. 발행자 서비스 배포·로컬 키/정책의 운영 격리는 제공하지 않는다.

요구사항 비교 QA ID는 `requirements_qa_task_id`로 명시하며 생략 시 QA ID 뒤 `-REQUIREMENTS`를 붙인다. criteria·원본 범위는 기존 requirement_lineage.configure_qa가 결정하고, 현재 lineage 계약이 개발계획 입력에 동결되어 있어야 한다. 이 비교 QA는 최종 구현 QA와 별도다.

허용된 별도 개발 보완 revision이 현재 실행 완료 근거를 가지며 같은 코드 범위를 수정하고 새 독립 QA retest가 통과하면 QA 범위 완료를 반환할 수 있다. 원래 구현의 오래된 검토는 복구하거나 승격하지 않는다. 공식 인증은 별도 현재 제출·발행자 계약을 계속 요구한다. 중단된 미완료 개발 자식에 별도 recovery admission이 필요하면 부모를 자동 재개하지 않고 차단한다.

선택 조회는 integration barrier와 원장 공유 lock으로 읽기만 한다. 각 action 시작의 authoritative refresh와 기존 실행·제출·검토 admission은 유지한다. 필드 조회마다 전체 Git 검증을 반복하지 않으며, 범용 검증 캐시나 context 압축을 추가한 것은 아니다.

역할 프로세스가 `waiting`과 questions를 반환한 의도적 checkpoint는 실행 중단이 아니라 WAITING_FOR_INPUT으로 보고한다. 입력을 기존 Decisions/native 질문 경로로 수집하고 기존 `Tasks.resume(task_id, agent_run_id, decision_file)`에 제공한 뒤 controller `resume`을 호출하면 같은 역할 실행을 이어간다. 이 decision 파일은 입력 근거일 뿐 HUMAN_APPROVAL이 아니다. 이미 등록된 required question은 현재 native answer 검증을 통과해야 하며, 임의의 새 선택지나 인간 응답을 controller가 생성하지 않는다.

### 통합 잠금 대기 예산

실행계약의 선택 항목 `lock_wait_timeout`은 bool을 제외한 정수 15~300초이며 기본값은 300초다. 계약 해시로 고정하고 정확히 같은 프로젝트 root의 하위 실행에만 전달한다. 기존 직접 실행의 기본 대기 15초와 명시적 timeout은 유지한다. EX 잠금·baseline·소유권·journal 검사는 생략하지 않으며 시간 초과 시 차단한다. 종료와 예외에서 환경 변수를 원래 존재 여부까지 복원한다. 프로세스 전역 환경 전달 때문에 한 Python 프로세스에서 public 컨트롤러를 동시에 호출하면 차단한다. 별도 CLI 프로세스의 feature별 실행 소유권은 기존 TaskLease가 관리한다. 대기 예산 확대는 무제한 재시도나 성능 보장이 아니다.

보완 후 원래 구현의 실행 증거가 오래되어 BLOCKED로 유지되는 경우, 그 상태를 DONE으로 복원하지 않는다. 원래 구현의 실행 receipt, 같은 범위의 별도 보완 작업의 현재 실행 receipt, QA 재검증 기록과 현재 observation receipt가 모두 유효할 때만 기존 QA 계약 및 완료 게이트로 계속 진행한다. 이 예외는 QA 범위 판정이며 공식 인증 검사를 대체하지 않는다.
