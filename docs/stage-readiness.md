# 독립 단계 검토와 보완 재시도 (개발 소스)

기획 확정, 디자인 확정, 개발계획 검토는 서로 다른 계약이다. 역할 입력 해석 수신증이나 문서 존재만으로 개발계획을 승인하지 않는다. 새 계약은 기존 작업 원장 tasks.yaml의 stage_workflows에 명시적으로 등록하며 별도 상태 원장은 만들지 않는다. 설치된 v0.2.0에는 아직 적용하지 않았다.

| 단계 | 별도로 등록해야 하는 필수 검토 |
|---|---|
| 기획 | 요구사항, 범위·정책, 수용 기준 |
| 디자인 | 화면 구성, 상태별 표현, 상호작용 |
| 개발계획 | 모듈 분해·경계, 작업 의존성, 실행 가능한 검증 명령 |

각 항목은 해당 단계 문서 작업의 실제 필수 criterion ID에 연결한다. configure-stage-workflow는 누락/중복 기준, 역할·프로젝트·작업 종류 불일치와 입력 해석 수신증의 계획 대체를 거절한다. 이 최소 검토 항목은 제품 요구사항을 임의로 추가하는 것이 아니며 프로젝트별 내용 판정은 실제 검토 근거가 필요하다.

## 실행 경로

1. Tasks.configure_stage_workflow(feature_id, stages)로 각 단계의 별도 작업과 필수 검토를 등록한다.
2. Tasks.bind_stage_inputs(task_id, inputs, reason)으로 현재 검토된 상위 산출물 버전을 명시적으로 연결한다. 이전 입력·검토는 보존한다.
3. 기존 ready → begin → submit → review 명령을 사용한다. 필수 FAIL/NOT_RUN이면 같은 단계의 READY 보완 작업이 생성된다. 검토 결과에 return_stage와 reason을 명시하면 해당 담당 단계로 반환한다. 자유 문장으로 반환 대상을 추측하지 않는다.
4. 보완 작업은 .R1 등 새 작업으로 남고 이전 DONE/PASS나 FAIL은 덮지 않는다. 기존 issues 목록·원래 finding 해소 검토를 재사용한다. 미해소 이슈는 다음 보완 작업으로 이어지며 해소에는 현재 출력과 이슈별 관찰이 있는 근거가 필요하다. 디자인 이슈는 기존 정책대로 실제 재렌더 캡처도 필요하다.
5. 수정 후 해당 단계 검토와 영향받은 후속 단계 검토를 다시 수행한다. 입력·출력·근거 해시, 검토 계약 해시와 승인 당시 상위 버전 연결이 모두 유효해야 PASS이다. 과거 계약 해시가 없는 PASS는 재검토 필요다.
6. 세 단계가 각각 유효하고 현재 승인 입력을 적용한 뒤에만 PRODUCT code_implementation ready/begin을 허용한다. 등록 계약 없는 신규 제품 구현도 차단한다. 단순 문서·설정·보고서 작업에 제품 코드 검증을 일괄 적용하지 않는다.
7. 원래 max_attempts를 보완 작업 전체에 합산한다. 한도 도달 시 BLOCKED_RETRY_LIMIT로 멈추며 사용자에게 추가 예산·범위 판단을 요청한다. 목표·정책·합의 변경 승인을 자동 발급하지 않는다.

보완 작업 생성·반환·기존 실행 종료는 원장/이벤트로 기록하고 대시보드는 이를 읽는다. task_registered/stage_rework_created의 정확한 run_id와 프로젝트·작업 종류 연결이 있을 때 실행 범위에서 보인다. 새 보완 작업의 실행 자체는 기존 작업 실행 명령이 담당한다. 독립 모델 프로세스를 자동 호출하거나 의미 검토를 자동 수행하는 기능을 구현했다고 주장하지 않는다.

대시보드의 단계 준비 상태는 구현 완료·제품 인수·사용자 승인과 별개다. 기존 메모앱에는 이 새 계약을 소급 등록하지 않았고 UNKNOWN을 유지한다. 개발계획 검토 통과도 구현/기능 회귀의 대체 근거가 아니다.

## 착수·재개 시 계약 누락 진단

PRODUCT 구현의 `ready`, `begin`, 체크포인트 `resume`은 같은 단계 준비 게이트를 적용한다. 계약이 없으면 단계 작업·필수 검토 등록 → 현재 버전 독립 검토 → 구현 입력 연결 순서를 안내하며 차단한다. `assess()`의 `UNKNOWN` 응답은 `next_actions`와 이 문서 경로를 함께 반환한다. 등록된 계약의 미통과 단계는 task ID·상태·차단 이유로 표시한다. 기존 개발계획 Markdown이나 소스 검토만으로 계약·PASS를 생성하지 않는다.

선택한 설치본의 기존 task 진입점을 사용한다. 원장이 비어 있으면 먼저 [설치용 작업 명령](task-management.md#cli와-역할-실행-범위)으로 새 계획·기획/문서 작업을 준비한다. 등록 인자 초안은 `docs/guard-inputs/`에 두고 제품 소스 작성 허가와 구분한다. JSON에는 실제 feature/task/criterion ID와 현재 파일 경로를 넣는다.

```sh
rtk proxy python3 .kmp-agent/agent.py task --run-id RUN --operation configure-stage-workflow --data docs/guard-inputs/workflow.json
rtk proxy python3 .kmp-agent/agent.py task --run-id RUN --operation bind-stage-inputs --data docs/guard-inputs/inputs.json
```

`workflow.json`은 `feature_id`와 `stages`를 지정한다. `stages`는 위 표의 `planning`, `design`, `development_plan`별 `task_id`, `checks`(검토 영역 → 기존 필수 criterion ID)다. 각 단계는 같은 프로젝트·feature·작업 종류의 별도 `documentation` 작업이어야 한다. 계약 등록 뒤 각 단계에 기존 `ready → begin → submit → review`를 실제 수행한다. 과거 PASS에 당시 계약 버전 연결이 없으면 현재 입력으로 재검토한다. `inputs.json`은 `task_id`, `inputs`(기존 원본 입력을 포함한 전체 입력 목록), `reason`을 지정한다. 현재 검토된 세 단계 산출물을 구현 task에 명시적으로 연결한다.

다음은 합성 ID를 쓴 입력 형태이며 실제 작업의 ID로 바꿔야 한다. UI 비해당 디자인 계약을 등록한 작업은 디자인 `checks`에 기존 계약의 `interfaces`, `inputs_outputs`, `errors`를 사용한다.

```json
{
  "feature_id": "FEATURE",
  "stages": {
    "planning": {"task_id": "PLAN", "checks": {"requirements": "P1", "scope_policy": "P2", "acceptance": "P3"}},
    "design": {"task_id": "DESIGN", "checks": {"screens": "D1", "states": "D2", "interactions": "D3"}},
    "development_plan": {"task_id": "DEV-PLAN", "checks": {"modules": "V1", "task_dependencies": "V2", "verification_commands": "V3"}}
  }
}
```

체크포인트가 살아 있는 작업은 입력을 덮어 재연결하지 않는다. 재개 게이트가 단계 보완이나 새 입력 연결을 요구하면 체크포인트를 보존하고 기존 `fail`로 해당 시도를 종료한 뒤 `bind-stage-inputs`, `ready`, 새 `begin`을 수행한다. 종료되지 않은 실행의 입력 변경을 허용하거나 과거 시작 근거를 재구성하지 않는다.

## 검증 범위

합성 임시 프로젝트에서 기획·디자인 PASS 뒤 개발계획 NOT_RUN 차단, 계약 미등록 구현 차단, 정확한 상위 입력 요구, 필수 검토 누락→보완→재검토, 디자인에서 기획 반환, 입력 변경의 후속 재검토, 보완 간 횟수 보존과 한도 차단, 과거 PASS 비승계, 입력 수신증 거절을 시험한다. 실제 메모앱 승인 근거로 사용하지 않는다. 브라우저 사례는 합성 기획 반환임을 별도로 표시한다.

진행 중인 대상 작업은 유효한 체크포인트 없이 반환하지 않는다. 마지막 허용 시도를 실행·검토 중인 상태는 한도 차단으로 조기 표시하지 않는다. 근거 없는 FAIL/NOT_RUN 반환은 해당 실패 검토를 인용한 NOT_PASSED 파생 근거로 남기며 PASS 근거로 승격하지 않는다.
