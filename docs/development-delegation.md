# 실제 개발 위임 실행

2026-10-27 개발 소스 기준. 기존 Tasks/agent_run/artifact/CR/snapshot/검토 상태를 재사용한다. 독립 역할을 일곱 개로 늘리지 않고 development 역할에 영역 축을 연결한다.

## 구성과 실행

1. 기존 개발 추적 계약으로 부모 코드 작업을 준비한다. 요구사항·디자인·API·정책 baseline과 실제 모듈 근거가 필요하다.
2. `Development(root, run_id).configure(parent_task_id, children, architecture, shared_owners, integration_commands, max_parallel=2, executable='codex', timeout=600)`로 위임한다. `Tasks.configure_delegation`도 같은 진입점이다.
3. 각 child에는 task_id/area/title/goal/requirement_ids/acceptance_ids/allowed_paths/dependencies/verification_commands/out_of_scope를 지정한다. architecture에는 evidence/modules와 실제 UI 소유권을 지정한다. 루트 빌드·공유 계약 파일의 담당자를 shared_owners에 명시한다. [시험 계약](../harness/test_delegation.py)을 실행 가능한 예로 사용한다.
4. 저장소 루트에서 다음을 실행한다.

```sh
rtk proxy python3 -B -m harness.cli --target /absolute/project development --run-id RUN_ID --task-id PARENT
```

명시적 계약이 없는 기존 development 호출은 입력 해석 경로를 유지한다. 작업을 자동으로 추측하여 제품 구현을 시작하지 않는다.

## 실행·통합

실제 Codex exec 독립 프로세스와 구조화 결과를 사용한다. 스폰·PID·종료·스레드 ID를 native agent_run에 연결한다. 역할 문서를 읽은 것을 서브에이전트 실행으로 세지 않는다. 각 작업은 로컬 Git 복제본과 분리된 빌드 캐시를 사용하고, 부모만 직렬 통합한다. 파일 겹침·소스 드리프트·범위 밖 변경·계약 변경은 사전 차단/반환한다. 선행 실패 시 후속 작업을 실행하지 않는다.

별도 프로세스 실행과 병렬 실행은 구분한다. 프로젝트 공유 `Tasks.configure_runtime_limits(max_parallel=2,max_executions=20)`은 모든 역할에 같은 슬롯·실행 admission 예산을 적용한다. CLI 한 번 안의 모델 응답 횟수나 토큰/달러 예산은 아니다. timeout은 각 호출에 적용한다. 재시도는 기존 이력과 최대 시도를 보존한다.

영역 검증과 별도 통합 검증을 모두 통과해도 READY_FOR_VERIFICATION이다. 독립 QA 및 제품 필수 인수 조건은 별도다. 과거 PASS는 기준/코드 변경 뒤 CURRENT인지 확인한다.

## 제약

임의 충돌 해결·삭제 전용 패치·완료된 구현을 자동 재수정하는 기능은 제공하지 않는다. 보완에는 승인 범위가 명확한 새 작업이 필요하다. 겹치는 허용 경로는 순차 작업이어도 보수적으로 거절한다. 상시 데몬·자동 원격 Git 작업은 없다. 실제 플랫폼 빌드 가능 여부는 프로젝트 환경에 달렸다.

[독립 QA](qa.md)의 검증 범위를 따른다. 합성 프로세스·실제 모델·플랫폼 빌드의 증거를 구분하고 실행하지 않은 검사를 완료로 승계하지 않는다.
