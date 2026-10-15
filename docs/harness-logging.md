# 최소 하네스 로깅 — 구현 상태와 한계

## 확인 결과

기존 저장소에는 로깅 문서만 있었고 실행기·프로젝트 로그는 없었다. 현재 [로거](../harness/logging.py)를 구현했다.
프로젝트 수집 시작은 **2026-10-13 03:14:57 UTC (12:14:57 KST)**다. 그 이전 실행은 아래 Codex 원본에서 확인된 사건만 가져왔다. 로거 생성 전 파일 변경 이력을 재구성하지 않았다.

- 프로젝트 로그: 저장소 루트의 `.harness/logs/events.jsonl`. 환경별 경로는 아래 로컬 설정 안내를 따른다.
- 기록 주체: `harness/logging.py`. CLI 실행 시작·체크포인트·종료·분류 이벤트·래핑 명령의 진입에서 기존 sync를 먼저 실행한다. Codex 훅 연결은 아래 활성화 범위를 따른다. 상시 프로세스는 없다.
- 원본 세션: 현재 환경의 Codex 세션 JSONL. 가져온 사건마다 절대 경로·줄 번호·원본 종류·원본 시각·가져온 시각을 보존한다.
- `.harness/`는 Git에서 제외된다. 저장 전 키·인증값·비밀번호·이메일 등 알려진 패턴을 마스킹하며 사용자 메시지는 마스킹된 내용만 저장한다. 임의 개인정보의 완전한 자동 탐지와 보존 기간 집행은 PLANNED다.

## 자동 측정과 에이전트 작성 정보

| 항목 | 현재 수집 방식 | 한계 |
| --- | --- | --- |
| 사용자 요청·후속 요청 | CLI 생명주기 또는 신뢰된 Codex 훅이 기존 sync로 마스킹 후 저장 | 의미 분류는 별도 에이전트 요약; 훅 신뢰 전·진입점 우회는 자동 보장 밖 |
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
실행 대상의 project_id·검증 범위는 [프로젝트 식별 계약](installation.md#프로젝트-식별검증-범위)에 따라 연결 설정에서 읽고 실행 컨텍스트로 전달한다. 식별 누락은 원인과 UNKNOWN으로 남기며 과거 이벤트는 재작성하지 않는다. status는 현재 컨텍스트와 기존 이벤트의 ID/범위별 그룹을 구분한다.
새 로거 실행의 종류는 HARNESS_BUILD / HARNESS_IMPROVEMENT / PRODUCT 중 선언한다. 과거 원본의 종류·역할·feature_id·task_id·agent_run_id는 근거가 없으면 UNKNOWN으로 둔다.
원본 턴 ID·응답 ID는 observed에 보존한다. 프로젝트 작업·에이전트 실행과의 자동 매핑은 PLANNED다.
이후 [최소 작업 관리](task-management.md)를 추가해 새 작업 이벤트의 네 ID 연결과 응답별 명시적 사용량 귀속을 지원한다. 원본 사건을 추정해 자동 매핑하지 않는다.

<a id="request-classification"></a>

## 사용자 후속·수정 요청 분류 — 에이전트 수행

원문은 아래 생명주기 수집 경로로 저장한다. 수행 Codex는 이전 요구·지침·산출물과 대조한 분류·판단 근거를 작업 관리의 intervention으로 선언한다. 원문이 먼저 수집됐으면 즉시 연결하고 늦게 수집되면 대기 후 연결한다. 원문 수집과 분류는 독립적이며 분류 실패로 메시지를 취소·삭제하지 않는다. 자동 의미 분류기·누락 감시기는 미구현(PLANNED)이다.

| 분류 | 기록 값 | 판단 기준 |
| --- | --- | --- |
| 요구 추가·변경 | REQUIREMENT_CHANGE | 처음에 없던 조건을 새로 요청 |
| 오류 수정·재작업 | CORRECTION | 이미 합의한 요구나 규칙을 어겨 수정 요청 |
| 진행 확인·설명 요청 | STATUS_OR_EXPLANATION | 상태나 결과를 이해하려고 개입 |
| 판단 보류 | UNKNOWN | 기존 요구와 비교할 근거 부족 |

수정이라는 표현만으로 CORRECTION을 부여하지 않는다. 한 메시지에 서로 다른 요청이 있으면 항목별로 구분하며 사용자에게 매번 분류 승인을 요구하지 않는다. 판단이 제품 방향·핵심 정책에 영향을 주는 경우만 기존 질문 규칙을 따른다.
정상 정책 답변·방향 선택은 기존 결정 근거로, 환경 장애·중단·재개는 기존 사건 로그로 유지하며 별도 요청 분류를 추가하지 않는다. 그 메시지에 후속 요청이 포함되면 위 네 기준으로 판단한다. 분류별 개입 횟수를 구분하고 네 분류 전체를 오류·누락 개입으로 합산하지 않는다.

기록은 `tasks.py intervention --data <JSON>`을 사용한다. 입력은 task_id, agent_run_id, session_id, turn_id, message_id, request_item, classification, basis, evidence다. basis는 기존 기대와 요청의 차이를 설명하고 evidence는 이전 합의·규칙·산출물 근거를 연결한다. 작업·실행 ID는 명시하며 역할·단계(work/review)·run_id·feature_id와 선언 당시 작업/디자인 상태는 기존 실행에서 가져온다. 다른 작업이나 최신 실행으로 추정 배정하지 않는다. request_item은 같은 턴·작업 실행 안의 개입 항목 식별자다. 같은 항목의 메시지 참조를 바꿔 재선언해 중복 생성하지 않으며, 기존 선언과 다른 참조·분류·근거는 거부한다.

선언은 human_intervention_pending에 남긴다. source_session_id·source_turn_id·source_message_id와 작업 실행을 보존하되 원문이 아직 events.jsonl에 없으면 연결 완료로 집계하지 않는다. message_id는 원본에서 확인한 실제 ID를 사용한다. 미확인은 UNKNOWN으로 남길 수 있으나 같은 세션·턴에 원문 후보가 둘 이상이면 연결하지 않는다. 이 경우 새 ID나 최신 메시지를 추측하지 말고 보류 사실을 보고한다. 환경 지침 메시지도 같은 턴에 있을 수 있으므로 실제 메시지 ID를 확인하는 것이 기본이다.

Stop 훅을 포함한 기존 sync는 원문을 먼저 저장한 뒤 새 pending 선언을 해소한다. 세션·턴·명시된 메시지 ID가 일치하는 단일 원문만 human_intervention으로 연결하며, 원본 메시지 ID·원문 이벤트 ID·출처·원본 시각, task_id·agent_run_id·역할·단계·분류·판단 근거를 함께 남긴다. 원문 ID·시각은 관측 근거이며 분류와 사유는 agent_declared다. 연결은 추가 이벤트이고 pending·원문·과거 이벤트를 재작성하지 않는다. 같은 선언/연결의 반복 실행은 중복 키로 한 번만 기록한다. 필수 연결이 없는 자유문 human_intervention 신규 기록은 거부한다.

집계는 연결 완료 human_intervention만 사용하고 pending은 별도 미연결 수로 보고한다. status의 interventions는 새 연결 완료·대기 ID·기존 자유문 미연결 이벤트 수를 구분한다. pending과 연결 이벤트를 두 개입으로 합산하지 않으며 UNKNOWN 분류를 오류 수정으로 합산하지 않는다. 같은 요청 항목의 재기록은 동일 ID·입력을 사용한다. 기존 선언과 다른 분류·근거를 같은 키로 덮어쓰는 것은 거부되며 분류 정정·소급 자동 보완은 미구현이다. 회고는 기존 선별 기준을 따르고 과거 요청·개입 로그는 추정으로 수정하지 않는다.

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

### 생명주기 수집과 보장 범위

[공식 훅 문서](https://learn.chatgpt.com/docs/hooks)와 설치된 codex-cli 0.162.1의 hooks=stable/true를 2026-10-15 확인했다. 프로젝트의 로컬 .codex/hooks.json에 UserPromptSubmit·Stop을 [codex_sync.py](../harness/codex_sync.py)로 연결했다. 설정은 Git 제외 대상이며 전역 notify는 유지한다. **정의 배치와 활성화는 다르다.** Codex의 /hooks에서 정확한 정의를 사용자가 검토·신뢰하기 전에는 실행이 보장되지 않는다. 신뢰 저장소를 직접 조작하거나 우회 플래그를 사용하지 않는다.

훅은 stdin의 session_id·transcript_path·cwd로 저장소와 원본을 확인해 기존 Logger.sync만 호출한다. 프롬프트 내용을 재작성하거나 사유를 분류하지 않는다. 원본 마스킹·ID·중복 키·Git 제외 규칙은 유지한다. 성공은 빈 JSON, 실패는 내용 없는 오류 종류와 비정상 종료로 보고하며 성공으로 숨기지 않는다. UserPromptSubmit 시 아직 세션 파일에 반영되지 않은 메시지는 Stop 또는 다음 수집에서 가져온다. 훅 payload의 prompt를 별도 메시지로 복제하지 않는다.

훅 설정은 실행하는 **각 저장소**의 `.codex/hooks.json`에 있어야 한다. 하네스의 프로젝트 설정·훅 신뢰는 형제 데모 저장소에 상속되지 않는다. 기존 개발 모드 데모는 공용 `harness/codex_sync.py`를 참조하는 설정만 두고 코드를 복사하지 않는다. 프로젝트 신뢰와 개별 훅 정의의 신뢰도 별개이며, 새 설정은 해당 저장소의 `/hooks`에서 검토·신뢰한다. 신뢰 상태 파일을 복사하거나 직접 수정하지 않는다. 개인 절대 경로가 포함된 개발용 `.codex/`는 Git에서 제외하며, 일반 설치의 경로 독립적인 프로젝트 훅은 [설치 규격](installation.md)에 따라 추적할 수 있다.

버전 설치·명시적 update는 [설치 절차](installation.md), 선택 버전의 연결 점검·재시작 판정과 자동 상태 갱신은 [연결 검증](harness-projects.md)이 기준이다. 원본 변경을 설치 대상에 자동 배포하지 않는다. 적용 점검 실패는 이미 수집한 원문을 취소하지 않으며 두 결과를 분리한다. 새 이벤트의 harness 필드는 로거 실행 당시 VERSION·실제 커밋·dirty·mode를 관측한 값이며 과거 모델 실행 버전을 소급 추정하지 않는다.

공용 스크립트는 프로세스 작업 디렉터리와 payload.cwd의 Git 루트가 같은지 확인하고 그 저장소의 `.harness/logs/events.jsonl`과 `hook-diagnostics.jsonl`에 기록한다. 스크립트가 놓인 하네스 경로를 로그 저장 대상으로 사용하지 않는다. `sync_started` 진단의 repository_root·events_path·harness_root로 실행 대상과 코드 위치를 구분한다. 진단은 원본 수집과 별개이며 원문과 시각을 만들어 채우지 않는다.

하네스 내부 테스트·하네스 세션 자동 수집 PASS와 데모 적용 검증은 별개다. 데모 적용 PASS에는 데모의 실제 새 사용자 요청, 원본 메시지 ID·세션 ID, 해당 세션 훅 진입·종료, 데모 events.jsonl의 일치 메시지 정확히 1건을 확인해야 한다. 설정 조회용 새 런타임의 hooks/list는 탐색·신뢰 확인일 뿐 기존 디자인 세션의 메모리에 로드됐다는 증거가 아니다. 기존 세션에서 미호출이면 같은 디자인 대화를 재개하거나 데모 루트의 새 세션에서 검증하고, 원래 세션과 새 세션 결과를 구분한다. 수동 sync·실제 원본을 넣은 훅 직접 호출로 이 검증을 대체하지 않는다.

2026-10-15 [데모 적용 검증](../.harness/logs/demo-hook-application.json)은 새 CLI 세션의 실제 일반 요청 자동 수집 PASS다. 기존 vscode 디자인 세션에서는 설정·신뢰 적용 뒤에도 훅 미호출이 관측됐으며 정확한 원인은 UNKNOWN이다. 동일 환경에서 검증하려면 데모 루트의 새 CLI 런타임을 사용한다(`rtk proxy codex --no-daemon --cd <데모 루트>`). 이 결과는 원문 수집에 한정하며 작업·역할 실행·개입 분류의 연결 PASS를 뜻하지 않는다.

훅 진단은 별도 `.harness/logs/hook-diagnostics.jsonl`에 기록한다. invocation_id로 process_entered → hook_entered → sync_started/finished → hook_exited를 연결하고 시각·이벤트 종류·세션/턴·스크립트 해시·원본 경로·파일 크기/마지막 사건 시각·프롬프트 존재 여부·가져온 수·종료 코드·마스킹된 오류를 남긴다. 원문 프롬프트·도구 출력은 복제하지 않는다. 진입만 있고 종료가 없으면 중단/타임아웃 가능성으로 남기며 종료 코드·원인은 UNKNOWN이다. 진입 자체가 없으면 미호출과 Python 시작 전 실패를 이 파일만으로 구분할 수 없으므로 런타임의 훅 목록·신뢰/활성 상태·오류도 함께 확인한다.

2026-10-15 사용자가 신뢰 완료를 확인했고 별도 설정 조회 런타임의 hooks/list에서 두 정의의 enabled=true·trusted·해시 일치·파싱 오류/경고 없음을 확인했다. 이는 기존 대화 메모리에 해당 정의가 로드됐거나 자동 호출됐다는 증거와는 다르다. 현재 대화의 hooks 기능 true도 정의 로드를 증명하지 않는다. 새 세션 필수 여부는 UNKNOWN이며 먼저 같은 대화의 정상 새 턴에서 확인한다. 진행 중인 턴의 질문 도구 답변·steer를 정상 새 턴의 수신 훅 검증으로 대체하지 않는다.

실제 검증에서는 수동 sync·CLI 생명주기·실제 원본을 넣은 훅 직접 호출을 사용하지 않는다. 한 턴 종료 후 사용자가 일반 메시지를 보내면 진단의 실제 hook_entered/종료 결과와 events.jsonl의 원본 메시지 ID별 건수를 각각 읽는다. 수신 시 원본에 없고 Stop 시 생겼다면 기록 지연의 근거이며, 두 훅을 거쳐도 메시지는 기존 키로 한 번만 저장돼야 한다. 실제 호출 근거 없이 단위 테스트나 CLI 수집 성공을 훅 자동 수집 성공으로 보고하지 않는다. 같은 대화의 정상 턴에서도 호출되지 않을 때만 재개/새 세션에서 비교하고 관측 근거를 기록한다.

훅 신뢰 전의 보완 경로는 logging.py CLI의 start/checkpoint/finish/event/command다. 실행 시 --session-path를 명시하거나 CODEX_THREAD_ID와 CODEX_HOME(기본 ~/.codex)의 sessions 아래 유일한 세션을 찾아 검증한다. 경로·세션 불일치/파일 부재는 해당 명령을 실패시킨다. 식별자·경로가 모두 없는 오프라인 실행은 경고하고 진행하므로 원문 수집 보장 밖이다. 이 경로는 해당 CLI를 실제 호출한 경우에 한하며 Logger.start/checkpoint 같은 Python API 직접 호출이나 작업 관리 명령 자체를 자동 수집기로 표현하지 않는다.

실제 런타임 훅의 신뢰·로드·전달, 중단/강제 종료, 타임아웃, 원본 파일 지연·형식 변경·소실, 디스크/권한 오류에서는 누락·지연이 가능하다. Stop 시점 뒤에 원본에 기록되는 최종 이벤트도 다음 수집이 필요하다. 살아 있는 원본이 있으면 재개·다음 시작으로 보완한다. 분류 실패와 무관하게 이미 수집한 마스킹된 원문은 남는다. 원문 수집·중복 방지는 자동화했지만 누락 감시·상시 파일 감시·자동 사유 분류는 미구현이다.

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
rtk proxy python3 harness/tasks.py intervention --data <원문참조·작업실행·분류·판단근거.json>
rtk proxy python3 harness/logging.py checkpoint <run_id> --result '중간 결과'
rtk proxy python3 harness/logging.py finish <run_id> --result '결과·제한'
rtk proxy python3 harness/logging.py status
rtk proxy python3 harness/logging.py audit <원본-세션.jsonl>
```

요청마다 CLI로 실행을 시작하고 checkpoint/finish를 사용한다. 이 진입점은 별도 sync 지시 없이 원문을 먼저 가져온다. 신뢰된 훅도 수신/종료 시 같은 sync를 호출한다. 필요 시 명시적 sync로 보완하며 다음 실행 시작에서 이전 턴 최종 결과·마지막 토큰을 가져온다.
체크포인트·종료는 시작 스냅샷과 비교한다. `finish`는 로거 작업 구간 종료이며 아직 전송하지 않은 최종 응답의 종료 시각을 만들어내지 않는다.
예외·충돌로 finish가 없으면 열린 실행으로 남으며 종료 시각을 추정하지 않는다.
CLI 생명주기의 세션 탐색은 현재 CODEX_THREAD_ID와 원본 메타데이터를 대조한다. 명시적 sync/audit와 복구는 실제 경로를 지정하며 다른 스레드 경로를 재사용하지 않는다.

`audit`는 실행 중 원본을 한 번 메모리에 읽어 고정한 뒤 가져오기를 준비하고, 동일 바이트를 두 번 더 동기화해 새 이벤트 0건·이벤트 수·토큰 합계 불변을 검증한다. 실행 중인 Codex 원본은 계속 증가하므로 고정하지 않은 두 시점의 수치가 달라도 중복 때문이라고 단정하지 않는다.
결과는 `.harness/logs/audit.json`, 마지막 동기화 시각·원본 끝 시각·수집 바이트/해시는 `last-sync.json`에 저장한다. 동기화 메타데이터는 이벤트 파일에 덧붙이지 않아 반복 동기화만으로 이벤트 수가 증가하지 않는다. 원본의 상세 복사본은 저장하지 않는다.

## 구현 확인

`rtk proxy python3 -m unittest discover -s harness -p test_logging.py`로 임시 디렉터리에서 확인한다.
시작·종료·파일 변경·중복 종료 거부, 종료 코드 7의 실패 명령 기록, 출처·원본 시간 보존, 중복 가져오기 방지, 미완성 마지막 줄의 다음 동기화 처리를 검증한다.
테스트 사건은 임시 로그에만 기록하며 실제 프로젝트 사용량으로 합산하지 않는다.
추가로 저장 전 마스킹·기존 로그 마스킹, 원본 ID·파일 위치 변경 후 중복 방지, 캐시 합산·누적 스냅샷 제외, 사용량 누락·충돌과 같은 원본의 반복 동기화를 검사한다.

최소 YAML 상태·의존성·검토·시도 상한 집행은 작업 관리에서 구현했다. 전체 역할 오케스트레이션, 상시 요청 수집, 시간·토큰·비용 예산 집행, 자동 변경 귀속, 비용 수집, 평가 자동화는 **PLANNED**다.
