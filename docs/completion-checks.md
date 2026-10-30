# 명시적으로 구성하는 완료 점검

이 기능은 **opt-in 신규 작업**의 필수 검토 PASS 직전에 사용량 연결과 맥락 검토 증거를 검사한다. 프로젝트 기본 정책으로 신규 작업에 자동 상속하거나 작업별로 명시 구성한다. 기존 미설정 작업의 완료 이력은 바꾸지 않는다. 서브에이전트 생성·사용자 정책 승인·전체 사용량 수집을 자동 보장하는 실행기는 아니다.

## 작업 시작 전

프로젝트가 `.harness/completion-policy.json`을 한 번 설정하면 지정 work type의 **새로 등록하는 작업**에 계약과 정책 파일 해시가 동결된다. 파일을 나중에 바꿔도 과거 작업은 재해석하지 않는다. 불명확한 버전·필드·경로는 부분 등록 없이 거부한다.

```json
{
  "version": 1,
  "apply_to_work_types": ["PRODUCT", "HARNESS_IMPROVEMENT"],
  "context_paths": ["AGENTS.md", "docs/context.md"],
  "usage_required": true,
  "context_required": true
}
```

이 파일은 제품별 맥락 경로를 지정하므로 하네스 릴리스의 특정 제품 경로로 고정하지 않는다. 의미 있는 변경을 하는 프로젝트는 이 기본 정책을 사용한다. 맥락 정리 담당 자신의 작업은 `context_required=False`와 반복 위임이 불필요한 이유를 명시하고 사용량 확인은 유지한다. 별도 재귀 서브에이전트를 만들지 않는다.

메인은 의미 있는 변경 작업을 등록한 뒤 TODO/READY 상태에서 필요한 맥락 경로를 지정한다. 작은 비모델·기계적 작업은 해당 요구를 해제할 수 있지만 구체적인 `exception_reason`이 필수다. 예외가 필요한 작업 범위만 한정하고 전체 기본값을 꺼서 누락을 숨기지 않는다.

```python
manager.configure_completion(
    'CHANGE', ['AGENTS.md', 'docs/context.md'],
    usage_required=True, context_required=True,
)
```

선택한 설치 진입점에서도 같은 기능을 사용한다. `completion.json`에는 위 인자 이름의 JSON을 넣는다.

```sh
rtk proxy python3 .kmp-agent/agent.py task --run-id RUN --operation configure-completion --data completion.json
```

## 사용량 등록·수집

작업을 시작한 메인 실행에 정확한 native session/turn 또는 response ID를 등록한다. ID를 모르면 UNKNOWN으로 남기고 확인한다. 작업 이름·시간 근접·같은 프로젝트 경로만으로 귀속시키지 않는다.

```json
{
  "session_id": "NATIVE_SESSION_ID",
  "path": "/actual/native/source.jsonl",
  "turn_id": "NATIVE_TURN_ID"
}
```

```sh
rtk proxy python3 .kmp-agent/agent.py usage-register --run-id RUN --task-id CHANGE --agent-run-id WORK_EXECUTION --data native-context.json
rtk proxy python3 .kmp-agent/agent.py usage-poll --run-id RUN
```

새 CLI는 명시된 메인 turn을 기본으로 제한해서 가져온다. `response_ids`로 정확한 응답 집합을 지정할 수도 있다. 독립 작업자는 기존 `WorkerStream`의 `thread.started` 또는 `usage_collection.register(..., independent=True, call_id=...)` 경로를 사용한다. 자식의 native `session_meta.id`/thread ID가 부모 `session_id`보다 우선하며 부모·자식을 하나로 합치지 않는다.

등록된 문맥은 hook 또는 full sync 후 자동 poll하여 원본 증분 사용량과 연결한다. 아직 원본 응답이 없거나 hook이 전달되지 않으면 다음 sync/poll까지 대기다. 등록하지 않은 세션·역할 전환은 자동 추정하지 않는다. 같은 응답의 복수 문맥·값 충돌은 미연결/격리로 남긴다.

완료 점검은 최신 work execution의 정확한 등록·원본 수치·바인딩을 검사한다. 하나라도 없거나 pending/충돌이면 `completion usage UNKNOWN`으로 PASS를 거부한다. 캐시·추론 상세와 누적 스냅샷은 추가 합산하지 않는다. 이 점검 시점 이후 새로 생성될 마지막 응답까지 미리 수집했다고 주장하지 않는다. 종료 hook 뒤 추가량은 같은 등록 문맥에서 갱신될 수 있다.

## 같은 native 턴을 여러 작업이 공유한 경우

사용자 후속 요청이 실행 중인 턴으로 들어오면, 서로 다른 작업에 같은 `session_id/turn_id`를 등록할 수 있다. 턴 하나를 두 작업의 전체 사용량으로 합산하지 않는다. 이 충돌은 미연결로 남기며 완료 점검도 계속 차단한다. 역할이나 작업을 바꾸면 정확한 response ID 집합을 등록하고, 같은 턴의 이전 소유 범위를 확인한다.

이미 겹친 broad 등록이 있다면 원본을 고쳐 쓰거나 완료 점검을 끄지 않는다. `usage_collection.revise_registrations`는 원등록 두 개를 명시하고, 원래 등록한 동일 native 파일의 고정 prefix 길이·SHA-256·실제 사용자 기록 위치와 정확 response 집합을 검증한다. 이전 작업의 기존 binding은 그대로 유지하고, 새 요청 뒤의 실제 응답을 현재 작업에 연결한다. 시간 근접·작업 제목으로 나누지 않는다.

```python
revision = revise_registrations(
    manager,
    supersedes=[previous_registration_id, current_registration_id],
    replacements=[
        {"registration_id": previous_registration_id,
         "side": "before", "response_ids": previous_bound_response_ids},
        {"registration_id": current_registration_id,
         "side": "after", "response_ids": current_native_response_ids},
    ],
    evidence={"source_path": registered_native_path,
              "source_bytes": fixed_prefix_bytes,
              "source_sha256": fixed_prefix_sha256,
              "boundary_line": actual_user_record_line},
    reason="확인된 native 사용자 요청 경계로 같은 턴의 작업 소유를 구분",
)
poll(manager)
resolve_attribution_limits(manager, revision["id"])
```

호출 전에 해당 prefix의 실제 `model_usage`를 수집해야 한다. 입력은 코드 예시의 이름을 추측해 채우지 말고 실제 원본에서 확인한다. `registration-revisions.jsonl`과 `attribution-resolutions.jsonl`에 감사 근거만 추가하며 `sessions.jsonl`, 원본 충돌, 기존 binding, DONE 결과는 보존한다. 원등록 파일 경로 불일치·수치 충돌·응답 누락·다른 소유 침범은 거부한다.

충돌 해소는 유효 등록·실제 usage·현재 단일 binding 소유가 일치하는 해당 충돌에만 적용한다. 위조·구식 해소 기록이나 새로 생긴 중복 소유는 계속 차단한다. 좁힌 범위 뒤에 생긴 응답은 같은 실행의 정확한 response ID로 별도 등록·수집한다. 고정 prefix의 정정 근거를 미래 응답의 자동 소유 선언으로 확대하지 않는다.

완료·출처·대시보드는 같은 유효 등록과 미해결 충돌을 읽는다. 조회는 요청 안에서 이미 읽은 전체 원장·이벤트·등록 검증을 공유하며, 표시 필터 때문에 전역 충돌 근거를 제거하지 않는다.

## 맥락 정리와 메인의 수락

메인이 [맥락 정리 담당](roles/context-maintainer.md)을 실제로 호출한다. 담당은 관련 문서를 대조·수정하고 결과와 제안을 반환한다. 메인은 이를 읽고 별도로 수락한다. 아래 보고서를 감시 대상 맥락 파일 자체로 지정해서 자기 해시를 다시 요구하는 구조는 허용하지 않는다.

```json
{
  "task_id": "CHANGE",
  "work_execution_id": "WORK_EXECUTION",
  "context_paths": [{"path": "docs/context.md", "sha256": "CURRENT_DOCUMENT_SHA256"}],
  "maintainer": {
    "result": "UPDATED",
    "reason": "확인된 변경과 남은 미결정을 현재 문서에 반영",
    "independence": "agent_declared",
    "proposals": ["아직 사용자 결정이 필요한 후속 정책"]
  },
  "main_review": {
    "accepted": true,
    "reason": "문서 변경을 읽고 구현 사실·사용자 결정·미결정이 구분됨을 확인"
  }
}
```

위 예제의 `context_paths`는 실제 configure에 지정한 모든 경로와 현재 해시로 바꾼다. `NO_CHANGE`도 실제 대조 범위·이유가 있어야 한다. 담당의 제안은 메인 수락이나 사용자 승인으로 간주하지 않는다. `agent_declared` 문자열은 native 독립 모델 실행의 증명이 아니다.

```python
manager.record_context_maintenance('CHANGE', work_execution_id, 'reports/maintenance.json')
```

```sh
rtk proxy python3 .kmp-agent/agent.py task --run-id RUN --operation record-context-maintenance --data receipt-arguments.json
```

`receipt-arguments.json`은 `task_id`, `work_execution_id`, `report_path`를 지정한다. receipt는 IN_PROGRESS/IN_REVIEW의 최신 work execution에만 기록한다. DONE 이력·이전 attempt의 receipt를 교체하지 않는다. 감시 문서가 검토 뒤 변경되면 해시 불일치로 PASS를 거부하며 새 검토가 필요하다.

## 보장 범위와 적용

게이트는 파일·해시·명시 등록·원본 사용량의 구조적 일치만 검사한다. 문서의 제품적 타당성과 실제 서브에이전트 호출 여부는 메인/별도 검토의 근거로 확인한다. `proposals`에 항목이 남았다고 자동 승인하지 않고 핵심 정책이면 관련 작업만 확인 전 보류한다.

수정된 코드를 테스트한 것과 적용 프로젝트가 그 커밋을 선택한 것은 다르다. 설치 사본을 덮어쓰지 않고 명시적인 설치/update 절차를 따른다. 선택하지 않은 과거 설치본에서 새 게이트가 동작한다고 보고하지 않는다.
