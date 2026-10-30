# 증거에 따른 완료와 재개

## 구현 전 대응표

기준: 공통 정책 작업 2ef4b0e 포함 로컬 clone. 앱 설치 799a4a5 유지.

| 요구 | 기존 구현·유지 | 이번 보강 |
|---|---|---|
| 작업 목표·범위·입력·선행·기준 | Tasks.register criteria/inputs/dependencies, execution_plan | 고정 검증 계약에 쓰기/금지 범위·통합 책임·기준별 방법/증거/플랫폼 |
| 누락 PASS 방지 | Tasks.review 모든 기준 정확히 1회, 필수 모두 PASS | 개별 기준별 실행 receipt, 다른 기준 결과 승계 차단 |
| 실제 코드 | development_tracking.capture HEAD+dirty+untracked+삭제+index+mode SHA | 그대로 재사용, HEAD만으로 대체 금지 |
| 독립 검증 | QA 격리 실행·명령·증거 복사, qa_policy 보완 기준 연결 | 작업/검토 실행 주체 분리, 실행 증거와 요구 완전성 검토 별개 |
| 플랫폼 절차 | 프로젝트 소유 runbook 참조 | Launch/Doctor/Drive/Evidence/Cleanup/Feature map 생성·검사 |
| 자원 충돌 | delegation 격리 clone·경로 충돌 검사, sequential 자원 선언 | 기존 task lock 내부 begin/resume 배타 검사 |
| 재개 | checkpoint·개발 추적 CURRENT/RECHECK_REQUIRED | raw DONE 대신 현재 코드·입력·증거 대조 |
| 보관 | SHA-256 frozen artifact | 누락/불일치/복구 가능 여부 진단, 외부 백업 보장 없음 |
| 현재 맥락·결정·로그 | tasks 원장·events·context 정책 | 원장 참조 유지, 중복 저장소 없음 |
| 대시보드 | 목표·단계·필수 기준·차단·상세 증거 | 검증 계약·플랫폼 및 증거 무결성 표시 |

## 현재 구현과 적용

사용자 요청은 누락된 검증의 완료 승격 방지다. 구현은 기존 task의 `verification_contract`, review의 `verification_evidence`, 기존 `validation_status`와 artifact 스냅샷을 사용한다. task 입력·출력·완료 기준·선행 작업을 복제한 별도 상태 저장소를 만들지 않는다. 기존 메모리 정책의 현재 맥락은 원장을 참조하고, 중요한 선택·실패·전환은 의사결정 기록, 상세 명령/출력은 기존 실행 로그에 남기는 책임 분리를 유지한다.

기존 프로젝트에 자동 적용하지 않는다. 이 코드가 포함된 배포/커밋을 명시적으로 선택해 설치·update한 후 새 세션의 startup/hook을 별도 확인한다. 이번 작업은 앱 설치 버전·제품 기능·원격 저장소를 변경하지 않는다. 프로젝트가 `.harness/verification-policy.json`을 다음과 같이 구성하면 이후 등록하는 해당 종류의 task에 계약이 필수가 된다.

```json
{"required_work_types": ["PRODUCT", "HARNESS_IMPROVEMENT"]}
```

정책 없는 프로젝트는 명시적 `configure-verification`으로 선택 적용한다. 정책 도입 전 task·과거 PASS는 계약 준수 결과로 소급 인증하지 않는다. 필수 정책을 상속한 새 task는 계약 없이 ready/begin할 수 없다. 계약은 실행 전 TODO/READY에서 한 번 고정하며 시작 후 필수 조건을 낮추는 재설정을 허용하지 않는다. 절차·환경 파일도 기존 inputs에 artifact로 연결한다.

## 계약과 실제 결과 연결

[프로젝트 절차](verification-procedures.md)를 먼저 작성하고, 프로젝트가 실제 환경 식별 내용으로 `qa/environment.json`을 준비한다. 환경 JSON의 의미상 정확성은 프로젝트 책임이다. 예를 들어 아래 `configure.json`은 기존 `TASK-1`의 기준 `AC-1`을 Web 사용자 동작 검증에 연결한다. 실제 task의 모든 기준을 정확히 한 번씩 정의해야 하며, 절차에서 필수인 각 플랫폼은 필수 실행 기준에 연결해야 한다.

```json
{
  "task_id": "TASK-1",
  "procedure": "qa/procedure.json",
  "environment": "qa/environment.json",
  "goal": "저장한 내용이 다시 열어도 유지되는지 확인",
  "integrator": "orchestrator",
  "writable_paths": ["src", "tests"],
  "forbidden_paths": ["qa", "requirements.md"],
  "criteria": [{"id": "AC-1", "platforms": ["web"], "method": "저장 후 다시 열기", "evidence_required": true, "kind": "execution"}]
}
```

```sh
rtk proxy python3 -B -m harness.tasks --root /absolute/project --run-id RUN_ID configure-verification --data configure.json
```

`begin` 데이터에는 구현·검토 각각 다른 `actor_id`를 명시한다. `configure-collection`의 `shared_resources`에는 기기·포트·데이터·브랜치 등의 정확한 공유 자원 키를 선언하고 공유 자원이 없으면 `[]`를 명시한다. 코드 작업은 기존 configure-development의 기준·code_paths 및 실제 코드 상태 추적을 함께 사용한다. 문서 검토에는 코드 해시를 발명하지 않으며 `code_state_sha256: null`을 사용한다.

PASS 검토 행의 evidence는 아래 필드의 JSON receipt 파일 경로다. `inputs`, `procedure_sha256`, `environment_sha256`은 `harness.verification.context(manager, task)`의 실제 값, `tested_outputs`는 task outputs의 경로→SHA-256, 코드 해시는 기존 `development_tracking.capture(manager, task)['state_sha256']`을 사용한다. 관찰 evidence 배열은 경로 문자열이 아닌 기존 `manager.artifact(relative_path)`의 반환 참조다.

```json
{
  "task_id": "TASK-1", "criterion_id": "AC-1",
  "review_run_id": "실제-검토-실행-UUID", "actor_id": "qa-reviewer",
  "inputs": {"requirements.md": "실제-SHA-256"},
  "procedure_sha256": "실제-절차-SHA-256", "environment_sha256": "실제-환경-SHA-256",
  "tested_outputs": {"src/example.py": "실제-산출물-SHA-256"},
  "code_state_sha256": "실제-작업트리-state_sha256",
  "kind": "execution", "method": "저장 후 다시 열기",
  "platform_results": [{
    "platform": "web", "result": "PASS", "environment": "실제 브라우저·빌드·포트 식별",
    "command_or_steps": "실제 실행 명령 및 저장·재열기 조작",
    "expected": "저장 내용 유지", "observed": "실제 관찰한 저장 내용 유지",
    "doctor": "PASS", "drive": "PASS", "cleanup": "PASS",
    "evidence": [{"path": "qa/evidence/trace.txt", "sha256": "실제-SHA-256", "snapshot": "실제-스냅샷-경로", "snapshot_sha256": "실제-SHA-256"}]
  }]
}
```

예시의 자리표시는 실제 값으로 바꿔야 한다. 기준마다 receipt를 따로 만들고 `review.json`에 `{"task_id":"TASK-1","agent_run_id":"실제-검토-실행-UUID","results":[{"criterion_id":"AC-1","result":"PASS","evidence":"qa/AC-1-receipt.json"}],"summary":"실제 관찰 요약"}` 형태로 전달한다. CLI는 같은 `harness.tasks`의 `review --data review.json`이다. NOT_RUN·FAIL·BLOCKED를 PASS receipt로 바꾸지 않는다. 하나의 기준 receipt를 다른 기준에 붙이거나 Server 결과로 Web·모바일을 대신하면 거부한다. `kind: requirements`는 요구사항/산출물 대응 검토이며 실행 검토를 대신하지 않는다.

기존 독립 QA 경로에도 `platform_results`를 제공한다. 각 행은 위 플랫폼 결과 필드를 사용하되 evidence는 격리 QA workspace 안의 상대 파일 경로 목록이다. QA는 이를 대상 프로젝트의 로컬 증거로 복사하고 artifact를 고정해 기준별 receipt를 만든다. 일반 PASS·빌드 성공·API 성공으로 플랫폼 결과를 추정하지 않는다. callable worker 시험과 실제 독립 모델 실행은 계속 구분한다.

## 현재 완료·재개 판정과 한계

필수 기준 누락/실패·대상 불일치·증거 누락/해시 불일치·필수 플랫폼 미검증은 완료 근거가 아니다. 코드·입력·환경·계약·증거의 현재 상태가 검토 시점과 다르면 기존 review를 지우지 않고 `RECHECK_REQUIRED`로 표시한다. resume-plan은 유효한 완료 작업만 건너뛰고 재검증 대상을 별도로 반환한다. 작업트리는 기존 HEAD·파일·index·mode 해시를 재사용하며 patch-id 기반 재사용 최적화는 없다.

artifact 진단은 `VALID`/`MISSING`/`HASH_MISMATCH`, `SNAPSHOT_AVAILABLE`/`SOURCE_AVAILABLE`/`UNAVAILABLE`을 구분한다. `archive: NOT_ESTABLISHED`, `automatic_restore: false`를 유지한다. 이는 로컬 파일 존재·해시 진단이며 별도 보관소, 자동 복구, 저장 장치 손실 복구를 구현하거나 보장하지 않는다. 기존 로컬 증거를 삭제·이동·원격 업로드하지 않는다.

공유 쓰기·실행 자원 검사는 기존 task lock 안의 begin/resume과 활성 자원 선언 변경에 적용한다. 같은 원장 안의 동일 repository 코드 구현 동시 쓰기와 같은 선언 자원 키 충돌을 거부한다. 종료하지 않은 checkpoint는 소유권을 유지한다. 다른 프로젝트 원장·raw shell·OS 프로세스 전체의 동시 실행은 통제하지 않는다. 실제 별도 clone/포트/데이터/기기 격리와 공통 계약 소비자 통합 검증은 담당자가 구성해야 한다.

actor_id 분리는 선언된 주체를 비교하는 검사이며 실제 별도 인간·모델·OS 신원의 증명은 아니다. receipt의 관찰 의미·화면 정상 여부·환경 정보의 진실성을 문자열과 해시만으로 증명하지 않는다. 실제 독립 QA 실행과 증거의 의미 검토가 필요한 경계다. 절차의 자유문 명령 안전성·제품 기대 결과의 타당성도 자동 판정하지 않는다. 기존 findings는 명시적 root_cause가 같은 작업의 반복 지적을 한 issue의 history에 보존하고, QA는 소유 역할·종류·reason_code·코드·기준·기대의 정확한 키로 연결한다. 의미상 원인 추론은 하지 않는다. confidence는 CONFIRMED/SUSPECTED를 구분하며 근거 부족을 정상으로 승격시키지 않는다.

pstack 기준 커밋 `4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`에서 create-verification-skill의 여섯 단계·정리 뒤 증거 보존, swarm의 작업별 쓰기 소유·누락 결과 제외, session-pickup의 과거 근거와 현재 산출물 대조를 선별했다. 역할/스킬 수·모델 기본값·별도 이벤트 원장은 도입하지 않는다.

참고: https://github.com/cursor/plugins/tree/4dd1d05818d19792e7cd6e818f1667f95f7e1dbe/pstack

쓰기 범위는 제출 산출물과 시작/제출 시 전체 로컬 파일 스냅샷 차이로 검사한다(기존 logger의 .git/.harness 및 설치 releases 제외 규칙). 선언 code_paths 바깥의 금지 파일 변경도 제출을 거부한다. OS 쓰기 자체를 차단하는 sandbox가 아니며 에이전트가 직접 수행한 raw shell을 감시하지 않는다. 자원 배타 검사는 계약 작업 또는 활성 계약 작업과 겹치는 작업에 적용한다. 기존 미구성 경로를 새 계약 준수로 표시하지 않는다.

## 잠금 진단과 실제 QA 인계 후속

원장 상태·소유권 검사는 계속 같은 잠금 안에서 수행한다. `tracking_io`는 Git 1회 5초·capture 전체 15초·원장 잠금 획득 10초의 기본 상한을 둔다. 잠금 획득 실패는 명시적 TimeoutError이며 과거 상태를 현재 PASS로 반환하거나 부분 상태를 쓰지 않는다. Git 시간 초과는 자신이 만든 프로세스 그룹만 종료·회수하고 불확실한 검증을 재검증 대상으로 남긴다. 로컬 파일 I/O와 원장 연산 전체의 강제 선점·OS 전체 중단을 보장하지 않는다.

capture는 immutable Git blob OID의 batch 조회로 파일별 프로세스를 제거한다. 같은 refresh 안에서는 task별 캡처만 재사용하고 mutation 전후 사이에는 재사용하지 않는다. 이미 RECHECK_REQUIRED인 과거 결과는 그대로 보존하며 자동 CURRENT 복귀가 없으므로 재캡처하지 않는다. binary·특수 파일명·삭제·untracked·staged·mode를 포함한 기존 state_sha256 의미는 유지한다.

`KMP_AGENT_DIAGNOSTICS=1`은 기존 프로젝트 `.harness/logs/inspection-diagnostics.jsonl`에 잠금 대기/획득/해제, capture, Git 실행/종료·elapsed를 raw 진단으로 남긴다. 작업 상태나 새 이벤트 원장이 아니며 상세 인자·환경 비밀값을 기록하지 않는다.

새 계약 owner의 완료에는 기존 `qa_repair` 인계 경로를 사용한다. 같은 target/owner task를 `QA.configure(...,repair_task_id=target,repair_criteria={owner_id:[qa_id]})`로 명시하고 실제 모델 QA를 실행한 뒤 `QA.accept_owner(qa_task_id)`로 인계한다. 각 owner 기준은 정확히 한 QA 기준의 동일 method/kind/platform 계약·절차·환경·실제 receipt에 연결해야 한다. 새 계약의 독립 provenance가 없는 callable 합성 QA는 이 완료 경로에서 거부된다. 이전 미구성 legacy 인계 정책을 실제 모델 실행으로 소급 승격하지 않는다.

작성자 receipt는 사람이 작성하지 않고 기존 실제 QA 관찰·artifact를 공통 어댑터가 정확히 변환한다. 최종 review의 원장 잠금 안에서 최신 QA 시도·기준 매핑·고정 정의·코드 범위·원본 receipt와 관찰 일치를 다시 검사한다. precheck 후 매핑 변경이나 관찰 변조도 거부한다. 인계가 검토 실행을 만든 뒤 실패하면 그 invocation이 소유한 실행만 기존 failure 경로로 닫는다. 이미 완료한 QA 재실행은 하지 않으며 코드가 바뀌면 정상 재개/제출과 별도 retest QA가 필요하다.

첫 후속 로컬 계측에서 파일이 적은 병렬 fixture는 기존 70.6초/1,526 Git 호출, 수정 후 77.1초/1,494 호출로 포괄적인 속도 개선이 아니었다. 파일 16개 capture에서는 state_sha256 및 기존 필드가 일치했고 23→8 Git 호출(0.83→0.28초)을 확인했다. 모든 숫자는 해당 로컬 합성 조건의 관측이며 제품 성능으로 일반화하지 않는다. raw 근거와 실제 모델 결과는 적용 프로젝트 로컬 후속 기록을 참조한다.

실제 모델 후속 실행에서 QA가 doctor/drive/cleanup에 `PASS: 설명`을 반환하여 exact PASS 게이트에서 차단된 사례를 확인했다. 모델 schema와 로컬 validator 모두 상태 필드를 PASS/FAIL/BLOCKED/NOT_RUN enum으로 제한한다. 설명은 observation/증거에 기록하며 자동 문자열 정규화나 기대 결과 완화는 하지 않는다. 실패한 실제 QA와 raw 증거는 보존하고 새 task/agent_run으로 재검증한다.
