# 최소 중단·재개 기록

[interruptions.py](../harness/interruptions.py)는 기존 로거에 증거를 추가한다. 중단 순간 에이전트가 기록하지 못했어도 재개 후 원본을 읽어 보완하며, 자동 복구·작업 재실행은 하지 않는다.
중단 때문에 종료·인계 회고를 남기지 못했다면 재개한 Codex가 확인 가능한 원본으로 [시행착오 요약](task-management.md#retrospective)을 보완한다. 시각·원인을 추정해 채우지 않는다.

## 기록과 근거 구분

중단·재개 이벤트는 모두 기존 run_id를 사용하고 `continuation_of_run_id`를 명시한다. `recorded_at`은 수집 시각이며 `occurred_at`은 사건 시각이다. 과거 사건을 현재 수집 시각으로 대체하지 않는다.

| 분류 | 저장 위치 | 의미 |
| --- | --- | --- |
| 자동 관측 사실 | observed + source.kind=codex_session_recovery | 원본 오류/중단 사건·다음 턴 시작의 시각, 원인·원본 ID·경로·줄 번호 |
| 사용자 진술 | user_statement + source.kind=user_statement | 사용자가 중단·재개 및 원인을 확인한 진술·출처; 정확한 시각 미제공 시 UNKNOWN |
| 에이전트 해석 | agent_summary | 어떤 원본 턴을 기존 실행의 연속으로 연결했는지에 대한 명시적 매핑 |

새 턴 시작은 자동으로 관측할 수 있지만, 그것만으로 이전 작업의 재개라고 단정하지 않는다. 사용자의 확인·업무 문맥을 바탕으로 중단 턴과 재개 턴을 명시적으로 지정한다. 원본의 오류 메시지는 사용자 진술과 별개로 보존한다.
원본에서 시각·원인을 확인하지 못하면 UNKNOWN이다. 사용자 확인만 있고 시각이 없으면 정확한 중단 시간을 계산하지 않는다. 단계 종료 시각이나 긴 공백을 중단 시각으로 대신하지 않는다.

## 사용법

안정적인 assertion-id 하나를 같은 중단 건에 계속 사용한다. 명령의 `<...>`는 실제 값으로 치환한다.

```sh
rtk proxy python3 harness/interruptions.py user-report <기존-run_id> --assertion-id <중단건-ID> --statement '사용자가 확인한 사실' --source '<사용자 메시지 참조>' --cause '사용자가 진술한 원인'
rtk proxy python3 harness/interruptions.py recover <기존-run_id> --assertion-id <중단건-ID> --session-path <세션.jsonl> --interrupted-turn-id <중단-turn_id> --resumed-turn-id <재개-turn_id>
rtk proxy python3 harness/interruptions.py timing <기존-run_id>
rtk proxy python3 harness/interruptions.py timing <기존-run_id> --scope-start <확인된-요청시작-UTC>
```

recover는 원본을 한 번 메모리에 읽어 기존 sync로 가져오고, 지정한 턴의 task_complete.error 또는 turn_aborted와 재개 task_started를 찾는다. 모호한 복수 사건이나 역순 시각은 거부한다.
원본 ID가 다른 두 턴을 같은 하네스 run_id에 연결하는 것이며 기존 실행 ID·단계 ID를 새로 만들지 않는다. 이미 종료된 실행에도 과거 증거를 추가할 수 있지만 종료 시각을 변경하거나 다시 열지 않는다.
resume_plan은 완료 작업을 건너뛸 목록과 미완료 상태만 반환한다. 현재 상태를 읽은 시각을 함께 남기며 과거 시점의 작업 상태인 것처럼 표현하지 않는다. 작업 실행·상태 수정은 수행하지 않는다.

## 시간 분류와 중복 방지

- 전체 경과: 기존 run_started부터 run_finished까지. 요청 시작을 근거로 별도 지정하면 그 범위도 계산한다. 종료 기록이 없으면 전체 경과는 UNKNOWN이다.
- 확인된 중단 간격: 원본 중단/오류 사건과 명시적으로 연결한 재개 사건의 타임스탬프 사이. 이는 원본 기록의 관측 간격이며 물리적 오류 발생 순간을 더 정밀하게 증명하는 값은 아니다.
- 단계별 경과: 기존 agent_run_id의 시작·종료. 중단이 단계 안에 있으면 단계 경과에도 포함되므로 겹치는 시간을 따로 표시한다.
- 미분류 시간: 전체에서 중단 구간과 단계 구간의 합집합을 제외한 나머지. 중단을 제외한 시간이나 단계 경과를 모두 실제 작업 시간으로 부르지 않는다.

사용자 진술만 있거나 한쪽 사건이 없으면 미확정 중단으로 남기고 확인된 간격만 하한으로 제시한다. 전체 중단 시간을 0으로 확정하지 않는다.
사용자 진술은 run_id·assertion-id·이벤트 종류로, 원본 사건은 run_id·원본 세션/사건 ID·종류로 중복을 막는다. 같은 사건의 반복 가져오기는 새 이벤트를 만들지 않는다. 시간 집계는 간격의 합집합을 사용해 중복·겹침을 다시 더하지 않는다.
기존 저장 전 마스킹, `.harness/` Git 제외, 로그 파일 접근 권한을 그대로 사용한다.

## 이번 시험 보정

기존 실행: `1317a3dc-ef9b-49bc-be46-aee3f20c062e`.
원본 세션에서 오류는 715행/ordinal 714의 task_complete.error이며 `server_overloaded`와 용량 오류 메시지가 있다. 재개 연결 대상은 717행/ordinal 716의 task_started다. 정확한 원본 경로·세션·턴 ID와 사용자 진술 근거는 `.harness/logs/trial-2-interruption-correction.json`에 보존했다.

| 항목 | 요청 시작 기준 | 하네스 시작 기준 |
| --- | ---: | ---: |
| 전체 경과 | 1,140.976초 | 1,124.615초 |
| 확인된 중단 간격 | 611.387초 | 611.387초 |
| 단계 경과 합집합 | 345.576초 | 345.576초 |
| 미분류 | 184.013초 | 167.652초 |

원본 오류 기록은 2026-10-13 05:59:01.489 UTC, 재개 연결 대상의 시작은 06:09:12.876 UTC다. 디자인 검토 종료부터 측정 종료까지 693.789초 전체를 중단으로 분류하지 않았다.
고정 원본의 재동기화 두 번 모두 추가 중단·재개 이벤트 0건, 전체 이벤트 수 748건 유지, 확인된 중단 간격 동일이었다. 완료된 TASK-003·TASK-004는 건너뛰었고 tasks.yaml 바이트도 유지됐다.

## 검증 범위·한계

`rtk proxy python3 -m unittest discover -s harness -p test_interruptions.py`로 중단·재개 복구, 출처 구분, UNKNOWN, 마스킹, 반복·이동된 원본 동기화, 간격 겹침, 역순 거부, 완료 작업 보존만 확인한다.
원본에 없는 장애의 시작·종료·원인을 자동 복원하지 않는다. 자동 재개 실행, 상태 복구 스케줄러, 독립 에이전트 호출, 대시보드는 PLANNED이며 이번 범위에 포함하지 않는다.
