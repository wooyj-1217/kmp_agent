# 최소 하네스 로깅 — 구현 상태와 한계

## 확인 결과

기존 저장소에는 로깅 문서만 있었고 실행기·프로젝트 로그는 없었다. 현재 [로거](../harness/logging.py)를 구현했다.
프로젝트 수집 시작은 **2026-10-13 03:14:57 UTC (12:14:57 KST)**다. 그 이전 실행은 아래 Codex 원본에서 확인된 사건만 가져왔다. 로거 생성 전 파일 변경 이력을 재구성하지 않았다.

- 프로젝트 로그: 저장소 루트의 `.harness/logs/events.jsonl`. 환경별 경로는 아래 로컬 설정 안내를 따른다.
- 기록 주체: `harness/logging.py`. 에이전트가 명령을 호출해야 동작하며 상시 프로세스·Codex 훅은 없다.
- 원본 세션: 현재 환경의 Codex 세션 JSONL. 가져온 사건마다 절대 경로·줄 번호·원본 종류·원본 시각·가져온 시각을 보존한다.
- `.harness/`는 Git에서 제외된다. 저장 전 키·인증값·비밀번호·이메일 등 알려진 패턴을 마스킹하며 사용자 메시지는 마스킹된 내용만 저장한다. 임의 개인정보의 완전한 자동 탐지와 보존 기간 집행은 PLANNED다.

## 자동 측정과 에이전트 작성 정보

| 항목 | 현재 수집 방식 | 한계 |
| --- | --- | --- |
| 사용자 요청·후속 요청 | `sync`가 원본 메시지를 읽어 마스킹 후 저장 | 후속 수정·의도된 결정·오류 개입의 의미 분류는 에이전트 요약 |
| 실행 ID·시각 | 로거 UUID·UTC 시작/종료, 원본 턴 ID·시각 | 로거 실행 구간과 전체 Codex 턴 구간은 별개; 현재 턴 종료는 다음 sync 필요 |
| 수행 역할·작업 종류 | start의 agent_summary에 에이전트가 선언 | 실제 별도 역할 프로세스가 실행됐다는 증거가 아님 |
| 변경 파일 | 시작·체크포인트·종료 또는 래핑 명령 전후 SHA-256 비교 | 변경 관측만 의미; 작업 완료·검증 PASS의 근거가 아님. 변경 주체 귀속·중간 원복 감지 불가 |
| 실행 결과 | 명령 종료 코드·출력 해시 자동 기록, 의미상 결과는 agent_summary | 모든 도구의 상세 출력·중첩 실행 종료 코드는 자동 해석하지 않음 |
| 도구 호출 | sync로 호출 ID·이름·원본 해시, item 시각 수집 | 도구 인자·출력 원문은 복제하지 않음; 상세는 원본 세션 참조 |
| 실패·중단 | 래핑 명령 종료 코드·예외, 원본 turn_aborted | 의미상 재시도·재작업·개입 원인은 수동 event 요약 |
| 토큰 | 원본 token_usage_record의 응답별 실제 usage | 입력·출력·캐시 입력을 각각 집계. 누적값·별도 token_count 스냅샷은 합산 제외 |
| 비용·모델 호출 시간 | UNKNOWN | 원본 응답 사용량에 제공되지 않음; 턴·명령 시간과 모델 호출 시간은 구분 |

`observed`는 로거가 측정하거나 원본에서 가져온 값이다. `agent_summary`는 에이전트 작성이며 자동 측정값으로 취급하지 않는다.
`recorded_at`은 프로젝트 로그에 기록한 시각이고 `observed.occurred_at`은 원본 사건 시각이다.
새 로거 실행의 종류는 HARNESS_BUILD / HARNESS_IMPROVEMENT / PRODUCT 중 선언한다. 과거 원본의 종류·역할·feature_id·task_id·agent_run_id는 근거가 없으면 UNKNOWN으로 둔다.
원본 턴 ID·응답 ID는 observed에 보존한다. 프로젝트 작업·에이전트 실행과의 자동 매핑은 PLANNED다.
이후 [최소 작업 관리](task-management.md)를 추가해 새 작업 이벤트의 네 ID 연결과 응답별 명시적 사용량 귀속을 지원한다. 원본 사건을 추정해 자동 매핑하지 않는다.

## 원본 ID와 중복 방지

`source.session_id`, `source.record_ordinal`, `source.native_ids`에 원본 세션·레코드 순번·메시지/호출/응답/턴 ID를 보존한다. 원본에 별도 event_id가 없으면 source.event_id는 원본 ordinal을 사용하며 새 UUID를 원본 ID인 것처럼 제시하지 않는다.
프로젝트 event_id는 별도로 생성한 UUID다. 가져오기 중복 키는 원본 세션 ID와 ordinal이며 파일을 옮겨도 유지된다. ordinal이 없는 형식은 레코드 콘텐츠 해시를 사용한다.
기존 프로젝트 로그는 `migrate`로 알려진 패턴을 마스킹하고 원본에서 확인한 ID·누적 스냅샷을 보완했다. 원본 Codex 세션은 변경하지 않는다.

## 토큰의 단위·원본 필드·계산

앞서 보고한 응답 44개는 사용자 턴이 아니라 서로 다른 `response_id` 44개, 즉 관측된 모델 응답 44개다. 한 사용자 턴에 도구 호출 전후 여러 모델 응답이 발생할 수 있다. 네트워크 시도·실패 요청까지 포함한 전체 호출 수라는 뜻은 아니다.

이 세션의 `token_usage_record.payload.usage`는 **응답별 증분**이다. 고유 response_id별 usage의 합이 마지막 `payload.thread_token_usage`와 일치하는지 audit에서 검증한다. `turn_token_usage`와 `thread_token_usage`는 누적 스냅샷이다.
각 응답까지의 증분 합도 해당 시점의 thread_token_usage와 대조한다. 현재 어댑터는 로컬에서 확인한 이 형식을 대상으로 하며 다른 제공자의 usage 의미를 자동으로 추정하지 않는다.
`event_msg`의 `token_count.info.last_token_usage`에는 같은 응답 증분이 반복되며 `total_token_usage`는 스레드 누적값이다. 이들은 출처 확인용으로 저장하되 합산하지 않는다.

- 입력 = 고유 `(session_id, response_id)`별 `usage.input_tokens`의 합.
- 캐시 입력 = 같은 응답들의 `usage.cached_input_tokens` 합. 입력의 부분집합이며 입력·전체 합계에 다시 더하지 않는다.
- 출력 = `usage.output_tokens` 합. 추론 출력 세부도 다시 더하지 않는다.
- 전체 = `usage.total_tokens` 합. audit에서 입력 + 출력 및 최종 스레드 누적값과 대조한다.

동일 응답의 같은 사용량 보고는 한 번만 집계한다. 서로 다른 값이 오면 충돌·누락으로 표시하며 임의의 보고를 선택하지 않는다.
필드 누락은 UNKNOWN이며 알려진 소계와 누락 필드 수를 함께 보고한다. 식별된 응답 중 사용량 없는 수와 응답 자체를 관측하지 못한 호출 수는 구분한다. 후자는 호출 시작 기록이 없으므로 UNKNOWN이다.
현재 조사에서는 token_usage_record와 token_count가 같은 사용량을 반복 보고하는 것을 확인했다. audit.json의 source_usage_records·source_unique_response_ids·source_duplicate_response_reports와 responses_also_repeated_in_token_count를 각각 보고해 동일 종류의 중복과 다른 종류의 재보고를 구분한다.

## 저장 전 마스킹

관측값·에이전트 요약·가져온 메시지·메타데이터 모두 저장 전에 같은 마스킹 함수를 거친다.
대상은 인증·비밀값 키, Bearer, API 키 패턴, JWT, PEM 개인키, 비밀번호 할당, URL 인증정보, 이메일이다. 도구 인자·출력 원문은 저장하지 않고 해시만 보존한다.
프로젝트 로그 디렉터리는 0700, 파일은 0600으로 제한한다. 패턴에 잡히지 않는 민감 정보까지 완전히 제거한다고 보장하지 않으며 로그 공유 전 별도 확인이 필요하다. 원본 세션의 접근·보존 정책은 Codex 환경 소관이다.

## 사용 절차

<a id="local-setup"></a>

### 로컬 설정 안내

개인 저장소·도구·Codex 세션 경로는 Git에서 제외한 docs/local-environment.md에 필요할 때 작성한다. 파일은 배포되지 않으며 없어도 공통 지침을 읽을 수 있다. 실제 하네스 루트와 데모 루트, 현재 원본 세션 경로·확인 근거, 환경별 도구 요구사항을 기록하고 다른 세션의 경로를 재사용하지 않는다.
형제 배치는 하네스 루트와 ../kmp_agent_demo_app을 사용한다. 데모를 실행 루트로 쓸 때 하네스의 기존 스크립트를 --root <데모 루트>로 호출하며 복사하지 않는다. 현재 실행 코드는 rtk와 Python 표준 라이브러리, POSIX fcntl을 사용한다. 로컬 절대 경로·인증 정보·원본 세션·실행 로그는 커밋하지 않는다.

중단 순간 기록을 남기지 못한 경우에는 [중단·재개 복구 절차](interruption-recovery.md)로 기존 실행 ID에 원본 근거와 사용자 진술을 구분해 연결한다. 완료된 단계는 재실행하지 않으며 확인된 중단 간격·단계 경과·미분류 시간을 별도 집계한다.

명령은 저장소 루트에서 실행한다. 다음은 사용 형식이며 실제 run_id·세션 경로로 치환한다.

```sh
rtk proxy python3 harness/logging.py start --work-type HARNESS_BUILD --role orchestrator --request '요청 요약'
rtk proxy python3 harness/logging.py sync <원본-세션.jsonl>
rtk proxy python3 harness/logging.py command <run_id> rtk git diff --check
rtk proxy python3 harness/logging.py event <run_id> --type human_intervention --summary '출처·의도된 결정인지 오류 개입인지와 근거'
rtk proxy python3 harness/logging.py checkpoint <run_id> --result '중간 결과'
rtk proxy python3 harness/logging.py finish <run_id> --result '결과·제한'
rtk proxy python3 harness/logging.py status
rtk proxy python3 harness/logging.py audit <원본-세션.jsonl>
```

요청마다 실행을 시작하고, 작업 중·마지막에 sync한다. 응답 완료 이후 다음 실행 시작 시 다시 sync하여 이전 턴 최종 결과·마지막 토큰을 가져온다.
체크포인트·종료는 시작 스냅샷과 비교한다. `finish`는 로거 작업 구간 종료이며 아직 전송하지 않은 최종 응답의 종료 시각을 만들어내지 않는다.
예외·충돌로 finish가 없으면 열린 실행으로 남으며 종료 시각을 추정하지 않는다.
세션 자동 탐색은 공통 로거에 넣지 않았다. 실제 경로를 명시하고 현재 환경 확인은 로컬 지침을 따른다.

`audit`는 실행 중 원본을 한 번 메모리에 읽어 고정한 뒤 가져오기를 준비하고, 동일 바이트를 두 번 더 동기화해 새 이벤트 0건·이벤트 수·토큰 합계 불변을 검증한다. 실행 중인 Codex 원본은 계속 증가하므로 고정하지 않은 두 시점의 수치가 달라도 중복 때문이라고 단정하지 않는다.
결과는 `.harness/logs/audit.json`, 마지막 동기화 시각·원본 끝 시각·수집 바이트/해시는 `last-sync.json`에 저장한다. 동기화 메타데이터는 이벤트 파일에 덧붙이지 않아 반복 동기화만으로 이벤트 수가 증가하지 않는다. 원본의 상세 복사본은 저장하지 않는다.

## 구현 확인

`rtk proxy python3 -m unittest discover -s harness -p test_logging.py`로 임시 디렉터리에서 확인한다.
시작·종료·파일 변경·중복 종료 거부, 종료 코드 7의 실패 명령 기록, 출처·원본 시간 보존, 중복 가져오기 방지, 미완성 마지막 줄의 다음 동기화 처리를 검증한다.
테스트 사건은 임시 로그에만 기록하며 실제 프로젝트 사용량으로 합산하지 않는다.
추가로 저장 전 마스킹·기존 로그 마스킹, 원본 ID·파일 위치 변경 후 중복 방지, 캐시 합산·누적 스냅샷 제외, 사용량 누락·충돌과 같은 원본의 반복 동기화를 검사한다.

최소 YAML 상태·의존성·검토·시도 상한 집행은 작업 관리에서 구현했다. 전체 역할 오케스트레이션, 상시 요청 수집, 시간·토큰·비용 예산 집행, 자동 변경 귀속, 비용 수집, 평가 자동화는 **PLANNED**다.
