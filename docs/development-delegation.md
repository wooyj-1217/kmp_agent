# 실제 개발 위임 실행

2026-10-27 개발 소스 기준. 기존 Tasks/agent_run/artifact/CR/snapshot/검토 상태를 재사용한다. 독립 역할을 일곱 개로 늘리지 않고 development 역할에 영역 축을 연결한다.

## 구성과 실행

1. 기존 개발 추적 계약으로 부모 코드 작업을 준비한다. 요구사항·디자인·API·정책 baseline과 실제 모듈 근거가 필요하다.
   PRODUCT 코드 구현에는 [승인된 개발 제약](development-constraints.md)을 configure-stage로 동결한다. 정책을 명시한 비 PRODUCT 작업도 같은 계약을 적용한다. 자식은 부모의 단계 계약·입력과 정책 packet을 상속한다.
2. `Development(root, run_id).configure(parent_task_id, children, architecture, shared_owners, integration_commands, max_parallel=2, executable='codex', timeout=600)`로 위임한다. `Tasks.configure_delegation`도 같은 진입점이다.
3. 각 child에는 task_id/area/title/goal/requirement_ids/acceptance_ids/allowed_paths/dependencies/verification_commands/out_of_scope를 지정한다. architecture에는 evidence/modules와 실제 UI 소유권을 지정한다. 루트 빌드·공유 계약 파일의 담당자를 shared_owners에 명시한다. [시험 계약](../harness/test_delegation.py)을 실행 가능한 예로 사용한다.
4. 저장소 루트에서 다음을 실행한다.

```sh
rtk proxy python3 -B -m harness.cli --target /absolute/project development --run-id RUN_ID --task-id PARENT
```

## 승인된 개발 계획에서 이어 실행

단계 워크플로에 등록한 `development_plan` 작업은 `development-plan.md`에 설명과 `development-execution` JSON 블록 하나를 함께 작성한다. AI가 승인 입력을 읽어 이 계약을 작성하며 사용자가 별도로 `configure_delegation` 인자를 다시 만들 필요가 없다. 빠진 모듈·소유권·명령·정책은 기획/디자인 또는 프로젝트 결정으로 반환한다. 텍스트에서 추측해 실행 명령을 만들지 않는다.

기획·디자인·개발 계획 각각의 필수 검토가 현재 원본 해시로 PASS한 뒤, 메인/오케스트레이터는 **같은 개발 계획 task ID로 위 development 명령을 다시 호출**한다. 진입점은 완료된 계획을 단순 skip하지 않고 `harness.implementation_bridge`로 다음을 수행한다.

1. 현재 단계 승인·산출물·입력·검토 근거의 해시와 요구사항 출처를 확인한다.
2. 승인된 블록에서 별도의 `code_implementation` 부모 작업·개발 추적·프로젝트 단계 계약·영역별 위임을 구성하고 기존 Todo에 연결한다. 계획 작업의 문서 범위를 코드 범위로 바꾸지 않는다.
3. 기존 Development 실행기로 실제 영역별 수정·분리된 통합 검증을 진행한다. 실패/미실행/추가 결정은 차단하며 제품 QA·배포·머지는 별도다.

계획 JSON은 [개발 계획 템플릿](templates/development-plan.md#실제-구현-연결-계약)을 따른다. planning/design baseline은 해당 단계의 승인 출력이어야 하고, 정책·API·아키텍처 근거·설정 및 설정이 참조하는 계약 문서는 이미 검토한 계획 입력이어야 한다. PRODUCT에는 승인된 프로젝트 단계·기술 제약이 필요하며 제품별 결정을 새로 승인하지 않는다. 통합 인수 단계는 구현 위임과 합치지 않는다.

같은 계획을 재호출하면 연결한 구현 작업을 재사용한다. 완료 구현은 중복 dispatch하지 않고 현재 검증 상태를 반환한다. 중간 구성 실패는 생성된 기록을 보존하고 명시적 복구를 요구한다. 계획/선행 입력 변경·다른 작업 ID 재사용·활성 실행 중복은 차단한다. 새 계획 버전은 새 구현 task ID로 검토한다. 검토 API 자체는 프로세스를 스폰하지 않으며 상시 스케줄러나 자동 제품 전체 실행을 추가하지 않는다.

단계 워크플로에 등록되지 않은 기존 development 호출은 입력 해석 경로를 유지한다. 계약 없는 과거 계획을 실행 가능한 계획으로 간주하지 않는다.

## 실행·통합

실제 Codex exec 독립 프로세스와 구조화 결과를 사용한다. 스폰·PID·종료·스레드 ID를 native agent_run에 연결한다. 역할 문서를 읽은 것을 서브에이전트 실행으로 세지 않는다. 각 작업은 로컬 Git 복제본과 분리된 빌드 캐시를 사용하고, 부모만 직렬 통합한다. 파일 겹침·소스 드리프트·범위 밖 변경·계약 변경은 사전 차단/반환한다. 선행 실패 시 후속 작업을 실행하지 않는다.

별도 프로세스 실행과 병렬 실행은 구분한다. 프로젝트 공유 `Tasks.configure_runtime_limits(max_parallel=2,max_executions=20)`은 모든 역할에 같은 슬롯·실행 admission 예산을 적용한다. CLI 한 번 안의 모델 응답 횟수나 토큰/달러 예산은 아니다. timeout은 각 호출에 적용한다. 재시도는 기존 이력과 최대 시도를 보존한다.

영역 검증과 별도 통합 검증을 모두 통과해도 READY_FOR_VERIFICATION이다. 독립 QA 및 제품 필수 인수 조건은 별도다. 과거 PASS는 기준/코드 변경 뒤 CURRENT인지 확인한다.

### 구현 완료와 공식 인증

새로 등록한 `execution_scope: code_implementation` 작업과 새 위임 구성에는 `completion_semantics: implementation_qa_v1`을 기록한다. 기존 상태 이름과 원장 형식은 유지한다. 코디네이터는 자식과 부모를 `Tasks.review(..., purpose='execution')`으로 검토하며, 이때의 `DONE`은 구현 실행·통합 범위의 완료다. `execution_completion` receipt와 정확한 코드 상태를 보존한 뒤 QA에 인계할 수 있다. 보호 발행자가 없어도 이 인계는 가능하지만 공식 인증 PASS를 만들지 않는다. 위임·개발 추적이 없는 임의 작업에는 이 검토 목적을 사용할 수 없다.

공식 인증은 별도의 명시적 검토이며 기본 `purpose='official'`을 유지한다. 현재 구현 receipt가 있는 DONE 작업은 검토를 다시 시작할 수 있지만, QA·관리자 승인·보호 증거가 없거나 현재 코드와 다르면 공식 완료가 차단된다. 구현 receipt의 코드·입력·증거가 오래되면 현재 DONE도 재검증 대상으로 차단한다. 구현 완료, QA 관찰 PASS, 관리자 공식 인증과 사람의 제품 방향 승인은 서로 대체하지 않는다. 상세 조건은 [보호 검증](protected-verification.md)을 따른다.

유효한 구현 실행 receipt에 한해 검토 범위·파일 내용·파일 모드가 모두 같으면 제출 commit으로 HEAD/index가 바뀐 것만으로 무효화하지 않는다. 이미 `RECHECK_REQUIRED`인 과거 판정은 이 예외로 자동 복원하지 않는다. 파일·모드·범위 또는 입력·증거 변경 검사는 유지하며, 공식 검토와 보호 인증은 제출 commit·tree·해시의 정확한 일치를 계속 요구한다.

기존 저장 작업에는 새 의미를 일괄 소급 적용하지 않는다. 과거 DONE과 `LEGACY_UNCERTIFIED` 이력은 공식 인증으로 승격하지 않는다. 다음 QA 호출·공식 검토는 여전히 명시 호출이며 자동 오케스트레이션은 추가하지 않는다.

승인 제약이 있으면 계획의 UI 소유권은 정책과 같아야 하며 통합 명령은 선택한 모든 타깃의 승인 명령을 포함해야 한다. 자식의 금지 소스 패턴 검사와 부모의 필수 패턴·진입 파일·UI 경로 검사를 구분한다. 통합 증거는 제출 work 실행에 연결된 native 명령 시작/종료·argv·출력 digest와 대조한다. 웹 누락이나 실행 불가를 PASS로 바꾸지 않는다. integration_verification은 별도 제품 인수 단계이며 구현 위임으로 대체하지 않는다.

## 제약

임의 충돌 해결·삭제 전용 패치·완료된 구현을 자동 재수정하는 기능은 제공하지 않는다. 보완에는 승인 범위가 명확한 새 작업이 필요하다. 겹치는 허용 경로는 순차 작업이어도 보수적으로 거절한다. 상시 데몬·자동 원격 Git 작업은 없다. 실제 플랫폼 빌드 가능 여부는 프로젝트 환경에 달렸다.

[독립 QA](qa.md)의 검증 범위를 따른다. 합성 프로세스·실제 모델·플랫폼 빌드의 증거를 구분하고 실행하지 않은 검사를 완료로 승계하지 않는다.
