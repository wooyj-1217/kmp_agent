# 빠른 훅 수집과 명시적 후처리

UserPromptSubmit/Stop은 원본 확인 → 세션 잠금 → 증분 변환 → 일괄 이벤트 저장/fsync → 커서 원자 갱신으로 끝난다. 의미 분류, 개입 연결, 집계, 전체 진단 탐색, 프로젝트 검사를 자동 연쇄 실행하지 않는다. 기존 120초 설정을 늘리지 않는다. 수집 하위 프로세스는 110초 내부 예산이며, 잠금 획득은 각각 10초, 진단 잠금은 2초 이내에 실패를 보고한다. 실패는 다음 명시적 실행/정상 훅에서 재시도하며 상시 작업자는 없다.

## 저장과 재시도

- 공식 원본은 기존 `events.jsonl`이다. schema_version=2, source_key, UUID, sequence, 마스킹·이벤트 형식은 유지한다. 기존 로거와 같은 이벤트 파일 잠금을 사용한다.
- `.harness/logs/cursors/<session-id의 SHA256>.json`과 `.lock`은 세션별 파생 메타데이터다. 같은 세션의 처리 전체를 직렬화하고, 다른 세션은 이벤트 배치 쓰기만 직렬화한다.
- 커서는 완성된 줄의 바이트 offset·줄 수·턴/모델 문맥·이전 바이트 해시·파일 식별자를 보관한다. 개행 없는 마지막 줄은 유효한 JSON이어도 보류한다. 완성됐으나 잘못된 JSON은 실패이며 건너뛰지 않는다.
- 이전 구간은 JSON 재해석 없이 바이트 해시를 확인한다. **완전한 무읽기 증분은 아니다.** 중간 덮어쓰기 감지를 위해 기존 offset까지 순차 읽으며 이 비용을 prefix_check_bytes/seconds로 구분한다.
- 원본 교체·축소·해시 불일치·손상된 커서는 전체 재수집으로 전환한다. 원본과 기존 이벤트를 삭제하지 않고 같은 식별자로 중복을 제거한다. 수동 `--full`도 같은 경로다.
- 중복/sequence 준비와 마스킹·직렬화는 잠금 밖에서 한 번 수행한다. 잠금 안에서 파일 식별자·크기·mtime을 재확인하고 달라졌으면 다시 준비한다. 기존 이벤트 로그가 커질수록 배치당 한 번의 읽기 비용은 남는다.
- 배치 저장 의도를 `collection-batch-intent.json`에 먼저 확정한다. 쓰기 중 중단되면 정확히 일치하는 미완성 접미부만 이어 쓰며, 로그를 자르지 않는다. 충돌이나 알 수 없는 손상은 자동 수정하지 않고 실패한다. 이벤트 fsync 뒤 커서를 원자 교체하고 디렉터리도 fsync한다. 커서 전 중단은 동일 키 재실행으로 복구한다.
- 원본 ordinal이 있으면 기존 session+ordinal 키를 유지한다. ordinal 없이 내용이 완전히 동일한 행을 구별하지 못하는 기존 content-hash 방식도 유지한다. 교체 원본이 동일 ordinal의 의미를 바꾸는 경우 기존 이벤트를 덮어쓰지 않는다.

## 명시적 명령

작업 저장소 루트에서 `<code>`는 설치한 하네스 코드 경로다. 개발 원본에서는 `.`이다. 명령은 설치한 버전의 코드를 사용하고 원본 경로는 해당 세션인지 확인한다.

```sh
# 빠른 수동 수집 / 별도 복구 (일반 훅과 구분)
rtk proxy python3 <code>/harness/incremental_sync.py --root . --mode manual <session.jsonl>
rtk proxy python3 <code>/harness/incremental_sync.py --root . --mode recovery --full <session.jsonl>

# 이전 훅의 후처리 대체: 필요한 단계만 명시적으로 실행
rtk proxy python3 <code>/harness/collection_maintenance.py --root . link
rtk proxy python3 <code>/harness/collection_maintenance.py --root . status
rtk proxy python3 <code>/harness/collection_maintenance.py --root . probe <session.jsonl>
rtk proxy python3 <code>/harness/collection_maintenance.py --root . projects --session-id <id>
# 기존 프로젝트 상세 확인/검증도 유지
rtk proxy python3 <code>/harness/projects.py check --target .
```

`link`는 기존 pending 선언과 수집된 원본을 연결한다. 의미 분류는 기존 에이전트 선언 절차로 수행한다. 일반 훅 성공만으로 pending 해소·집계 최신화·프로젝트 VERIFIED를 주장하지 않는다. `projects`는 기존 after_hook의 검사·상태 저장을 명시적으로 수행하고 배포/업데이트하지 않는다. 프로젝트 검증은 현재 파일을 다시 fingerprint하고 훅에 기록된 승인 manifest 캐시·실제 수집 스크립트 해시와 대조한다. 캐시 부재·불일치는 NOT_RUN으로 남는다.

기존 `logging.py sync/audit/status`도 보존한다. `sync`는 전체 원본 변환과 개입 연결을 포함하되 이벤트 쓰기·중복 검사는 같은 배치 저장기를 재사용한다. 빠른 훅 경로로 사용하지 않는다. CLI start/finish 등 기존 생명주기의 전체 sync·자동 연결 동작도 호환 목적으로 유지하며, 배치 저장 확정 뒤 last-sync 메타데이터를 기록한다. 중간 종료는 다음 전체 sync에서 같은 키로 재수집한다.

## 진단과 성공 판정

일반 훅은 `hook-diagnostics.jsonl`, 수동/복구는 `collection-diagnostics.jsonl`에 mode와 invocation_id로 구분한다. 잠금 요청·획득·해제, 변환 완료, 이벤트 durable, 커서 commit, 수집 완료/실패를 기록한다. 잠금 owner 파일은 마지막 관측 PID/상태이며 프로세스 생존 증거가 아니다. 기존 로거처럼 owner 메타데이터를 쓰지 않는 프로세스의 소유자는 UNKNOWN이다.

훅 래퍼는 수집 하위 프로세스의 종료 코드를 실제 수신한 뒤 `hook_exited`를 남긴다. `collector_ready`는 종료 증거가 아니다. hook_exited가 없으면 UNKNOWN이며 성공으로 보지 않는다. 래퍼 자체의 최종 종료는 외부 훅 실행기의 반환 상태로 확인한다. 과거 종료 마커를 소급 수정하지 않는다. 원문·도구 인자·출력은 진단에 기록하지 않는다.

코드 변경은 기존 훅 신뢰/정의 로딩과 별개다. 직접 호출 시험·수동 복구를 실제 Codex 자동 훅 실행 검증으로 표시하지 않는다. 설치는 기존 코드 스냅샷 전체를 사용하고 init이 생성하는 명령 래퍼의 hook 진입점도 같은 감독 경로를 사용한다.
