# 원본·승인 기준과 파생 명세의 일치 검토

격리 개발 소스에만 적용한다. 설치본·과거 원장은 변경하지 않는다. 별도 역할·상태 원장을 만들지 않고 Tasks artifact/snapshot/verification/agent_run/issue/review를 재사용한다.

## 입력 계약

프로젝트 루트 `requirement-lineage.json`:
- schema_version=1, scope=PRODUCT 또는 HARNESS_TRIAL, purpose.
- sources: id/kind/path/sha256/anchor. USER_ORIGINAL은 문자 그대로의 요청·결정, APPROVED_REQUIREMENTS는 approval.source/anchor/approved_sha256로 USER_ORIGINAL 승인·기준 지정을 연결한 요구, AGENT_DERIVED는 파생 설계·시험 명세. 파일명이나 에이전트 CONFIRMED는 권한 근거가 아니다. 해시는 내용 고정이지 사용자 권한 증명이 아니다.
- requirements: id/source/anchor/expected(값·동작 객체). 원문의 모든 요구 목록을 만든다. 추론·제안은 승인 요구로 승격하지 않는다.
- derived_items: id/source/anchor/source_ids/expected/excluded. 원본별 전체 기대값과 비교 가능한 단위로 분리한다. 원본 누락, 출처 없는 추가, 값/동작 변경, 제외를 계산한다.
- decisions: delta_id/status/source/anchor/expected/actual. APPROVED는 USER_ORIGINAL과 정확한 변경 전후 값이 필요하다. 구체 합의를 일반 기술 위임으로 바꾸지 않는다. 실제 승인 의미·출처 진위는 독립 QA가 확인한다.

PRODUCT의 미승인 변경은 보완/사용자 결정 대기로 반환한다. HARNESS_TRIAL은 purpose, USER_ORIGINAL 출처를 가리키는 scope_authorization, product_pass_claim=false, 각 차이의 TRIAL_ONLY+reason+정확한 전후 값을 요구한다. 제품의 원래 조건은 여전히 미충족이다. 제한 시험을 제품 변경 승인이나 제품 PASS로 바꾸지 않는다.

## 실행

부모 개발 task inputs에 계약·모든 출처를 넣어 동결한다.

```sh
rtk proxy python3 -B -m harness.requirement_lineage compare --root /project
rtk proxy python3 -B -m harness.requirement_lineage configure-qa --root /project --run-id RUN --task-id REQUIREMENTS-QA --target-task-id DEVELOPMENT
rtk proxy python3 -B -m harness.cli --target /project qa --run-id RUN --task-id REQUIREMENTS-QA
rtk proxy python3 -B -m harness.cli --target /project development --run-id RUN --task-id DEVELOPMENT
```

stage=requirements는 기존 verification 역할/QA.execute의 독립 프로세스·한도·결과 회수·반환 루프를 사용한다. 원문·승인 문서·파생 명세·구조 비교를 모두 전달하고 전체 원본 목록 자체의 누락도 읽어 검토하도록 필수 criteria를 등록한다. 누락·모순은 baseline_gap/baseline_contradiction으로 planning에 반환한다. QA가 정책을 수정하지 않는다.

실제 development와 직접 run_child(run_codex)는 모델 호출 전에 동일 부모 대상의 동결 계약·필수 기준·현재 입력/검토 범위·독립 QA 실행 시작/종료·유효 보고를 검사한다. 없으면 기존 task에 BLOCKED 이유/다음 행동과 이벤트를 기록한다. 계약이 있는 구현/재검증 QA도 선행 요구사항 QA를 검사한다.

기존 명시 synthetic worker 단위 시험은 유지하되 독립 QA로 인정하지 않는다. 계약 없는 과거 QA는 LEGACY_UNCERTIFIED. 실제 신규 development는 계약 없이 실행하지 않는다. 외부 메인 에이전트의 직접 파일 편집/하네스 밖 명령까지 통제하는 기능은 아니다. 설치본에는 미적용이다.

QA 보고는 claim_scope / requirement_lineage / execution_path_validation / product_requirements_fulfillment을 분리한다. 작업 QA PASS만으로 실행 경로나 제품 전체를 PASS로 승격하지 않는다. 플랫폼·영역·통합 인수는 별도다.

## 한계

구조 검사는 명시된 링크·값 차이·승인 참조·신선도를 확인한다. 자연어 의미·원본 인벤토리 완전성·사용자 출처 진위·승인 범위는 독립 QA의 직접 검토가 필요하다. source kind 라벨만으로 진위를 증명하지 않는다. 새 모델 호출은 이번 검증에서 하지 않았으므로 실제 모델의 의미 이해 성능 검증은 NOT_RUN이다. 합성 상태 시험과 실제 모델 검토 성공을 구분한다.

위 실행 명령은 해당 로컬 개발 소스를 이미 명시 선택한 격리 프로젝트에서만 사용한다. 실제 제품의 설치본 선택을 바꾸지 않는다. requirements QA는 기준 문서 범위만 고정하므로 정상적인 후속 구현 코드 변경만으로 원본 대조 QA를 무효화하지 않는다. 원본·파생·승인·계약 변경은 재검토를 요구한다.
