# 명시적 로컬 실행 복구 계약

세션 오류·재개 원문의 수집은 [중단 기록](interruption-recovery.md), 작업 실행의 소유권·복구·재시도는 이 계약을 따른다. `harness/recovery.py`와 `Interruptions.recover_tasks()/resume_plan()/resume_task()`가 명시 호출 경로다. 전체 목표를 자동 재개하는 스케줄러·오케스트레이터는 아니다. 기존 task 상태 enum과 승인·QA·공식 인증 경계는 유지한다.

## 상태와 명령

작업의 TODO/READY/IN_PROGRESS/IN_REVIEW/BLOCKED/DONE을 새 enum으로 바꾸지 않는다. 아래는 별도 recovery 판정이다.

| 판정 | 조건·효과 |
| --- | --- |
| `ACTIVE` | 실제 lease가 잡혔거나 정확한 owner가 살아 있음. 복구·중복 실행 거부 |
| `INTERRUPTED` | owner 사망·lease 해제·등록 자식 종료 확인. inspect 결과이며 아직 안전한 재개 승인은 아님 |
| `RECOVERABLE` | 현재 입력·작업공간이 시작 근거 및 현재 유효한 완료 자식 결과와 일치. checkpoint 저장, 작업 BLOCKED |
| `RECHECK_REQUIRED` | 입력·코드·근거 변경 또는 중단된 review 등 재검증 필요. 과거 PASS 복원 금지 |
| `MANUAL_INTERVENTION_REQUIRED` | owner·spawn·자식 그룹 근거가 없거나 불명확. 사망·종료를 추정하지 않음 |

```sh
rtk proxy python3 -m harness.interruptions --root /project resume-plan RUN_ID
rtk proxy python3 -m harness.interruptions --root /project recover-tasks RUN_ID --task-id TASK_ID
rtk proxy python3 -m harness.interruptions --root /project resume-task RUN_ID --task-id TASK_ID
```

`resume-plan`은 현재 유효한 DONE skip 목록·재검증 이유·소유권 판정만 읽는다. `recover-tasks`는 통합 journal을 먼저 복구하고 확정 중단 실행을 종료 기록·checkpoint로 보존하며 해당 작업을 BLOCKED로 둔다. 이때 `ended_at`은 복구 관측 시각이며 정확한 사망 시각이 아니다(`RECOVERY_OBSERVATION_NOT_EXACT_PROCESS_DEATH`).

`resume-task`는 유효한 RECOVERABLE checkpoint와 현재 workspace basis, 시도 한도를 확인해 재개 admission을 한 번 예약하고 역할·개발·QA의 기존 실행기로 명시 전달한다. 반복 예약은 거부한다. DONE 캐시는 현재 근거가 유효한 경우만 반환하며 공식 완료를 새로 추론하지 않는다. 원문 승인·실행 정책·1차 완료 receipt·2차 권한 검사를 면제하지 않는다.

## 실제 실행 소유권

`process_ownership.TaskLease`는 kernel flock과 PID birth/host 근거를 사용한다. JSON 존재·mtime·PID 숫자만으로 소유권이나 사망을 판정하지 않는다. managed adapter가 실행과 receipt를 연결하고, 등록된 자식은 전용 process group과 guardian으로 추적한다. guardian은 parent 사망 후 정확히 식별된 자식만 정리한다. 살아 있거나 신원을 확인할 수 없는 owner·그룹에는 복구를 진행하지 않는다. plain `Tasks.begin()`은 논리 실행일 뿐 물리적 owner를 만들지 않으므로 owner 없는 중단은 UNKNOWN·수동 확인 대상이다.

`Popen` 반환과 child 등록 사이의 spawn intent가 남은 창은 수동 확인한다. PID 확인과 signal 사이의 원자성, 탈출·새로 생긴 자손, same-OS 계정의 근거 변조까지 보장하지 않는다. 운영 root 서비스는 배포하지 않았다.

## 다중 파일 통합

`integration_transaction.apply()`는 전체 before/after bytes·mode snapshot, Git HEAD/index, baseline을 저장하고 PREPARED/APPLYING/COMMITTED를 기록한다. COMMITTED는 통합 기록이며 task DONE·공식 인증이 아니다. 미완료 journal이 있으면 일반 진행 게이트가 차단한다.

명시 `recover()`는 현재 전체 복구 집합이 알려진 before/after 중 하나이고 snapshot·HEAD/index·baseline이 모두 맞을 때만 rollback한다. 사용자 편집·모드 변경·다른 Git 상태·불명 journal이면 MANUAL로 보존하고 덮어쓰지 않는다. 각 파일 쓰기 직전에도 재확인한다. 반복 COMMITTED 요청도 같은 source map과 현재 증거가 맞을 때만 캐시를 반환한다.

## 원장과 이벤트

작업 원장은 fsync 후 atomic replace하며 outbox 이벤트의 source key를 유지한다. `durable_events.append_locked()`는 기존 events 파일 flock 아래 exact prefix hash와 append payload를 먼저 durable intent로 저장한다. read·일반 Logger·incremental 수집은 같은 lock과 recovery를 사용한다. partial write 이후에는 intent와 정확히 일치하는 누락 suffix만 이어 쓰고 중복 source key를 제거한다. 과거 collection intent도 호환한다. 알 수 없는 tail·변경된 prefix·충돌은 원본을 truncate하지 않고 보존·차단한다.

이 구조는 관측된 프로세스 중단과 재실행 복구의 계약이다. 전원 손실·저장장치 오류, 구버전 writer나 외부 raw append, standalone verification runner 강제 종료 후 운영 복구는 전체 검증하지 않았다. 같은 OS 계정이 원장·journal·snapshot을 함께 바꾸는 공격에 대한 보안 격리도 아니다. 로컬 합성 process 시험을 운영 전체 복구 PASS로 확대하지 않는다.

정상 통합과 중단된 journal은 구분한다. `Tasks._mutate()`는 입력·검증 refresh 이전부터 원장 저장까지 `integration_transaction.read_barrier()`로 같은 물리 통합 잠금을 유지한다. 직접 실행의 정상 writer는 기본 최대 15초까지 기다리며 (오케스트레이터의 동일 root 실행은 동결된 lock_wait_timeout 15~300초, 기본 300초를 적용), timeout은 실행 차단으로 처리한다. 잠금이 풀린 뒤에도 남은 미해결 journal만 명시 복구 대상으로 삼는다. writer 안에서 Tasks에 진입하는 잠금 역전은 거부하며, 복구의 live-writer 검사는 nonblocking으로 유지한다.

`Development.workspace()`도 같은 read barrier 안에서 clone·manifest·전체 파일 복사를 수행한다. 정상 sibling 통합의 a=after/b=before 혼합 snapshot을 실제 재현한 뒤, writer COMMITTED 이후 두 파일이 같은 settled 버전으로 복사되는 것을 확인했다. 외부 writer가 이 잠금을 따르지 않는 경우까지 원자성을 보장하지 않는다.

잠금 순서는 통합 read barrier → 원장 state lock이다. writer를 기다리는 동안 원장 잠금을 보유하지 않는다. 정상 writer를 12초 기다리는 두 독립 reader 시험에서, 역순은 두 번째 reader의 10초 state-lock timeout을 재현했고 이 순서로 두 reader가 모두 진행하는지 검증한다. 모든 대기는 유한하며 timeout을 성공이나 DONE으로 간주하지 않는다.
