# 순차 개발 근거 수집 — 현재 작업본의 최소 구현

이 기능은 순차 작업의 관측 근거와 누락을 보존한다. 병렬 실행·후보 판정·시간 절감 추정은 하지 않는다. 상세 병렬화 후보 분석기는 후속 작업이다. 배포 전 작업본 기능이며 기존 `v0.1.0` 설치에 자동 추가되지 않는다.

상태·역할 실행은 기존 `.harness/tasks/tasks.yaml`, 명령·대기·통합 사건은 기존 이벤트 로그, 입력·설정·증거는 기존 artifact snapshot을 사용한다. 제품별 실제 기록·보고서는 해당 프로젝트 `.harness/`에만 저장하며 하네스 원본으로 자동 전송하지 않는다. 별도 제품 버전 번호나 추적 DB를 만들지 않는다.

## 설치·초기 설정

이 기능이 포함된 검증된 릴리스를 [명시한 ref로 설치·업데이트](installation.md)한 뒤 제품 루트에서 실행한다. 기존 `v0.1.0`에는 아래 명령이 없다. 0.2.0 미배포 후보는 고정한 임시 로컬 Git 전체 SHA로도 시험한다. 개발 작업본 시험에서는 `bootstrap.py install --target <임시 프로젝트> --dev-source <하네스 원본>`을 사용할 수 있으며 정식 설치·배포 검증과 다르다.

```sh
rtk proxy python3 .kmp-agent/agent.py init --tracking-settings docs/sequential-settings.json
```

[설정 예제](templates/sequential-settings.json)를 제품 모듈·명령에 맞춰 한 번 작성한다. 저장 위치는 `.harness/settings/sequential.json`이다. 이후 init·update와 작업 실행에서 재사용한다. 설정 변경은 같은 옵션으로 명시적으로 다시 등록한다. 이름 있는 명령은 신뢰한 로컬 argv이며 셸 문자열·자동 실행·환경/비밀 값 주입을 지원하지 않는다. 제품의 환경 준비와 비밀 값은 기존 실행 환경에서 관리한다. `cwd`와 모듈 경로는 제품 루트 상대 경로다.

설정 등록만으로 빌드·테스트를 실행하거나 임의 셸 명령을 감시하지 않는다. Codex 원문 훅의 신뢰·활성화 확인도 별도다. 모듈 경로 매핑은 파일 소속의 선언이며 수정 주체·읽기 의존성을 증명하지 않는다.

## 기존 작업 실행에 연결

선택한 설치본 진입점의 `task --operation <기존 명령> --data <JSON> --run-id <run>`은 기존 Tasks API를 사용한다. 기존 `harness/tasks.py --root ...` 호출도 호환된다. 원문 요청 수집·개입 연결은 [기존 절차](harness-logging.md#request-classification)를 계속 따른다.

```sh
rtk proxy python3 .kmp-agent/agent.py start --request '개발 작업 요약'
rtk proxy python3 .kmp-agent/agent.py task --run-id <run> --operation register --data task.json
rtk proxy python3 .kmp-agent/agent.py task --run-id <run> --operation configure-collection --data collection.json
rtk proxy python3 .kmp-agent/agent.py task --run-id <run> --operation ready --data task-id.json
rtk proxy python3 .kmp-agent/agent.py task --run-id <run> --operation begin --data begin.json
```

`collection.json` 예시:

```json
{
  "task_id": "IMPLEMENT-1",
  "dependency_relations": [
    {"task_id": "CONTRACT-1", "kind": "REQUIRED", "reason": "확정된 API 계약을 입력으로 사용"},
    {"task_id": "DOC-1", "kind": "ORDER_ONLY", "reason": "운영상 먼저 처리; 구현의 필수 입력은 아님"}
  ],
  "shared_modules": ["shared"],
  "shared_resources": ["local-test-db"],
  "feature_version": "UNKNOWN"
}
```

REQUIRED 집합은 기존 task.dependencies와 일치해야 한다. ORDER_ONLY는 실행 게이트에 추가되지 않는다. 실행 순서로 의존 관계를 생성하지 않는다. 의존 이유·모듈·자원은 역할 선언이다. 명시한 빈 목록은 없음이라는 선언이고 누락·UNKNOWN과 다르다. 실행 중 보완하려면 활성 `agent_run_id`를 추가한다. 시점이 있는 별도 선언 이력으로 남으며 시작 기준을 소급 수정하지 않는다. 피처/기준 식별자는 시작 전에 지정한다.

각 새 agent_run의 `attempt_id`는 기존 고유 agent_run_id를 재사용한다. checkpoint/resume은 같은 시도이고 새 역할 실행·검토는 별도 시도다. 시작에 실제 하네스 runtime version/commit/dirty/mode, 입력 snapshot 묶음의 해시 식별자를 고정한다. 명시한 feature_version/baseline_id가 있으면 함께 보존한다. feature_id·서비스 URL 버전·하네스 배포 버전과 다르며 새 버전 번호를 발급하지 않는다. 수정된 개발 원본에서는 commit만으로 코드 전체를 재현할 수 없으므로 dirty도 함께 확인한다.

## 명령·대기·통합

begin 결과의 실제 ID를 사용한다. 이름 있는 명령을 사용하면 명령 유형·cwd·argv를 매번 지정할 필요가 없다.

```sh
rtk proxy python3 .kmp-agent/agent.py command --run-id <run> --task-id <task> --agent-run-id <agent> --attempt-id <attempt> --command-name unit-test
```

일회성 명령은 `--argv-json '["rtk","proxy","python3","-m","unittest"]' --command-kind test`를 사용한다. 유형은 development/build/test/integration/other/UNKNOWN이다. 명령 시작·종료 UTC, monotonic 경과 시간, 반환 코드와 파일 변화를 기록한다. 명령 출력은 터미널로 전달하고 로그에는 출력 해시를 저장한다. 비정상 종료나 수집 중단으로 종료 근거가 없으면 누락/UNKNOWN이며 성공·0초로 처리하지 않는다.

ID를 전혀 지정하지 않은 래퍼 명령은 기존 호출과 호환하되 MISSING으로 표시한다. 일부 ID만 지정하거나 다른/종료/차단된 실행을 지정하면 거부한다. 동일 시간대라는 이유로 귀속하지 않는다. 래퍼 밖 명령의 전체 수·누락 수는 UNKNOWN이다.

대기는 기존 checkpoint JSON에 `wait_type`(DEPENDENCY/RESOURCE/DECISION/EXTERNAL/OTHER/UNKNOWN)과 `wait_target`(작업·자원·결정 식별자 또는 UNKNOWN)을 추가한다. 시작 시각과 선언 이유를 기록하고 resume 시 RELEASED, fail 시 CANCELLED로 닫는다. 종료 시각이 없으면 열린 대기다. 실행 경과 시간은 대기를 포함하며 실제 개발·모델 계산 시간으로 해석하지 않는다. checkpoint는 실행 재개를 지원하며 **코드 복원을 보장하지 않는다**.

통합·충돌·재작업이 실제 발생하면 `task --operation integration --data <JSON>`을 사용한다. 필드는 task_id, agent_run_id, kind(INTEGRATION/CONFLICT/REWORK), reason, evidence(기존 파일), 선택적으로 cr({folder,id}), before_commit, after_commit, conflict_files다. CR은 기존 변경 요청이며 해당 작업이 impacts.tasks에 있어야 한다. 증거는 기존 artifact로 고정하고 실행 및 이벤트에 연결한다. 미확인 커밋·충돌 파일·원인은 UNKNOWN으로 남긴다. 사건이 없다는 기록 없이 누락을 0건으로 해석하지 않는다. 자동 Git 병합·충돌 해결은 하지 않는다.

## 자동 관측과 역할 책임

| 자동 수집 경로 | 역할·운영자가 제공해야 하는 내용 |
| --- | --- |
| begin/submit/fail/review의 시작·종료 파일 해시 차이, 설정 snapshot·입력 묶음·하네스 식별 | 의존 종류·이유, 공유 모듈·자원, 제품 피처 버전(알 수 없으면 UNKNOWN) |
| command 래퍼의 명령 구간·반환 코드·변경 파일 | 래퍼 사용과 정확한 task/agent_run/attempt, 설정 밖 명령 유형 |
| checkpoint/resume/fail의 대기 경계 | 대기 유형·대상·이유, 실제 재개/취소 호출 |
| 기존 리뷰·CR·명시적 사용량 바인딩 참조 | 통합/충돌/재작업 원인·증거·해당 CR, 응답 사용량 귀속 근거 |

코드 작업의 파일 관측 범위는 기존 development_tracking.code_paths를 재사용한다. 그 외는 로거 snapshot 제외 규칙을 사용한다. 시작 이전 dirty 변경이나 경계 사이에 변경 후 되돌린 내용은 실행 수정으로 재구성하지 않는다. 수정 주체는 항상 UNKNOWN으로 두고 경계 차이만 관측한다. 설정이 있어도 누락된 역할 선언을 추정 생성하지 않는다. 공통 역할 문서·실행 context·인계에서 이 절차를 재사용하므로 제품마다 별도 추적 프롬프트를 작성할 필요가 없다.

## 수집 충족도

```sh
rtk proxy python3 .kmp-agent/agent.py collection-report
```

기존 상태·이벤트를 읽어 COLLECTED(수집됨)/MISSING(누락)/UNKNOWN과 원본 경로·agent_run·event ID를 출력하고 제품 `.harness/logs/sequential-coverage.json`에 저장한다. 과거 task·이벤트·시작 기준을 갱신하지 않는다. 선언 시점이 늦으면 시작 시 고정된 값과 후속 선언을 구분한다. 사용량은 기존 명시 바인딩 근거만 연결하며 전체 사용량·비용을 추정하지 않는다. 병렬화 판정은 NOT_EVALUATED, 시간 절감은 UNKNOWN이다. 보고서 생성 당시의 읽기 관측이며 동시에 변하는 상태·로그 전체의 트랜잭션 snapshot은 아니다.

검증: `rtk proxy python3 -B -m unittest harness.test_sequential`은 임시 적용 프로젝트 설치·init·설정 재사용·작업 실행·명령·제출·보고와 누락·호환성을 검사한다. 실제 제품에서의 수집 완전성과 Codex 훅 활성화 증거는 별도로 확인한다.

## 배포 전과 적용 프로젝트 업데이트

배포 전에는 기존 미커밋 변경과 이번 변경의 범위를 검토하고 관련 회귀 테스트를 통과시킨다. 선택할 릴리스의 정확한 코드·VERSION/ref/commit과 지원 현황을 확정한 다음, 개발 원본 참조가 아닌 고정된 배포 후보에서 설치 → init → 실제 코드 작업/명령 → 미커밋 제출/검증 → 보고 → 업데이트 설정 보존을 재검증한다. 그 근거를 릴리스 지원 문서에 남긴다. 이번 개발용 임시 프로젝트 시험을 원격 릴리스 설치·실제 제품 검증 완료로 표현하지 않는다. 커밋·태그·푸시·정식 배포는 별도 승인 범위다.

해당 기능이 배포된 후 제품에서 명시한 버전을 선택한다.

```sh
rtk proxy python3 .kmp-agent/agent.py update --source <하네스-원격-저장소> --ref <기능이-포함된-태그-또는-전체-SHA>
rtk proxy python3 .kmp-agent/agent.py init --tracking-settings docs/sequential-settings.json
rtk proxy python3 .kmp-agent/agent.py collection-report
```

설정이 이미 등록된 제품은 `init`만 실행해 재사용한다. 제품의 기존 task·로그·snapshot은 유지하며 새 실행부터 수집한다. 과거 누락은 그대로 남긴다. 훅 수집을 사용하는 경우 신뢰/활성화와 실제 수신 증거도 기존 연결 점검으로 확인한다. 이후 역할은 공통 지침과 등록 명령을 사용하며 별도 제품 추적 프롬프트를 반복 입력하지 않는다.
