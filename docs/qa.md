# QA execution contract

QA is an alias of the existing **verification** role, not a seventh role. Planning,
design, implementation and retest QA tasks use native task IDs, executions, frozen
artifacts, criteria, reviews and issues. QA completion is distinct from feature
completion or development integration approval.

`QA(root, run_id).configure(task_id, stage, target_task_id, original_requests,
criteria, commands=None, max_attempts=2, repair_task_id=None)` registers a native
verification documentation task. Stages are `planning`, `design`, `implementation`,
`retest`. `original_requests` must identify real repository files; these are frozen
separately from agent-authored target inputs. Criteria require `id`, `description`,
`required`; a visual criterion may add `visual_required: true` or `kind: visual`.
Commands are argument arrays, never shell strings.

`QA(...).execute(task_id, worker=None, repair=None)` starts a real independent
Codex process through the existing process/logging adapter when worker is omitted.
A callable worker is an explicit deterministic/test adapter and is **not** a model
execution. Runtime failure becomes BLOCKED and the native run is closed. Each
attempt and review remains in native history. A second start cannot duplicate an
active run or rerun a completed QA task.

## Read-only product boundary

QA receives an isolated copy. It may create evidence in `qa-tools/`, private
harness state and process caches; changes to product files invalidate the result.
Actual verification commands run in that same copy, with stdout/stderr and exit
code frozen as evidence. Product symlinks are refused. The source manifest is
checked before and after execution. The runtime uses `workspace-write` to create
QA evidence, not permission to change product code; violations are detected and
BLOCKED rather than integrated. This does not provide OS isolation for a malicious
custom Python worker injected by its caller.

## Findings and acceptance

The strict result schema separates criterion PASS/FAIL/BLOCKED/NOT_RUN from
findings: specification violation, baseline gap, baseline contradiction, usability
and optional improvement. Findings carry owner, requirement/design/contract IDs,
expected/actual behavior, reproduction, code/baseline references and evidence.
A blocking baseline gap or contradiction remains BLOCKED for its owner; QA does
not invent missing product policy. Optional suggestions do not create mandatory
acceptance conditions.

PASS requires all required criteria, actual existing evidence for every claimed
PASS, unchanged product content, successful configured commands and no blocking
finding. Visual criteria additionally require an actual PNG/JPEG/WebP capture.
The report preserves the model's claims separately. Native final review here is
a **local evidence check**, not an independent model approval. Existence and image
headers cannot prove semantic correctness; that remains the QA model/user review
boundary. A report cannot claim feature-wide integration success from this task.

Native issues retain the original QA classification in `qa_finding`. They attach
to the reviewed target, with `qa_task_id` for provenance. They are not silently
resolved by a repair callback. Registered stage workflows may create a bounded
owner-stage return; unregistered projects receive issues without inferred stage
approval. Creating a repair task is not completing the repair.

## Bounded repair and retest

An optional `repair(attempt, worker_result, root)` callback is an explicit owner
operation outside QA. It must return `status: COMPLETE` plus a real `evidence`
path before another attempt. The repair is recorded as
`REPORTED_COMPLETE_NOT_VERIFIED`; the next QA execution must verify the result.
The original failed review, frozen inputs, repair proof and a separate current
retest manifest remain available. Max attempts bounds automatic repeats. Without
a callback QA reports findings and stops; it does not modify product files.
The low-level callback API treats `repair_task_id` as linkage. The configured CLI owner path below validates an explicit repair task before executing it; neither linkage nor a repair report grants quality approval.

## Local tests

```
rtk proxy python3 -B -m unittest harness.test_qa
```

The suite uses callable workers and isolated temporary files. It covers evidence,
actual command exit results, missing commands, immutable product boundaries,
missing original requests, changed baselines, duplicate starts, bounded retries,
blocking policy gaps, visual evidence and failure-preserving repair/retest. These
are deterministic contract tests; real model execution is a separate experiment.

### Retest provenance and issue resolution

Configure may also store `executable` and `timeout`. Explicit execute arguments
may override them. The QA packet includes native target issues, earlier QA
attempts and current target state, alongside the immutable original requests.
Model results carry `reviewed_issue_ids` (an empty list when none). Omitting the
field remains compatible with local callable fixtures and never closes issues.

After an owner repair, QA freezes fresh target input files, records old/new
`input_rebases`, and distinguishes the target's declared baseline from observed
current content. Original request files must remain unchanged; changing them
stops automatic retest for a user-authority decision. Repairing a specification
to match an already explicit original policy is distinct from inventing policy.

An issue closes only if it originated in QA for the same target, the model
explicitly reviewed its ID, all required QA criteria and actual command gates
passed, native QA review is DONE, and the target manifest is still identical.
Resolution preserves the issue and records QA execution/review IDs, report proof
and exact code manifest. A successful QA result without explicit reviewed IDs
leaves existing issues OPEN.


## Configured CLI owner path

`QA.configure(..., repair_task_id=OWNER_TASK, executable=NATIVE_CODEX, timeout=600)`
explicitly configures the bounded owner workflow. The owner must already be a
matching native task for the same project/feature/work type and returned role.
The canonical invocation is:

```sh
rtk proxy python3 -B -m harness.cli --target /absolute/project qa --run-id RUN_ID --task-id QA_TASK
```

`qa` and `verification` select the same native role. In this path `qa_repair`
invokes an independent owner process, guards original requests and allowed output
paths, submits IN_REVIEW, then invokes fresh QA. Only independent QA evidence can
finish the owner review. Previously completed delegated implementation is blocked
until a separately authorized repair revision is configured. Missing policy is
returned rather than invented. All model processes share runtime_limits slots
and the native run's process admission budget; this is not a token/dollar cap.

실제 모델의 기획 누락·담당 보완·재검증과 결정적인 합성 설계/구현 시험은 별도로 검증한다. 각 실행의 입력·명령·결과 근거를 보존하고 합성 시험 통과를 실제 모델 시험으로 승계하지 않는다.


## Actual image and execution context

QA.configure images/context_files freezes artifacts separately from verbatim original_requests and includes them in source scope. Images use actual Codex exec --image transport with hash metadata; only in-workspace PNG/JPEG/WebP with matching suffix/bytes are accepted. Context changes block before dispatch. Each evidence field must identify exactly one actual relative file, with extra references inside that file. Invalid evidence cannot become PASS even when model prose says pass. Actual model review, execution-evidence review, model-executed commands and synthetic tests remain distinct.


## 기준 대응과 프로젝트별 생성물 설정

`task configure-qa --data ...`의 기존 JSON에 다음 선택 필드를 사용한다.

```json
{
  "generated_paths": ["client/build", "server/build"],
  "repair_criteria": {
    "OWNER-AC-001": ["QA-001"],
    "OWNER-AC-002": ["QA-002", "QA-003"]
  }
}
```

`repair_criteria`는 보완 작업의 기준 ID → QA 기준 ID 목록이다. 기준 정의와 연결을 QA 보고서에 고정하고 각 QA 결과·검토 실행·검증 근거를 보완 검토 증거에 연결한다. 매핑된 QA 기준이 모두 PASS이고 근거와 현재 대상이 일치할 때만 해당 보완 기준을 PASS로 제출한다. 연결 누락, 기준 정의 변경, 근거 누락/변경, QA 이후 대상 변경은 NOT_RUN이다. QA 전체 PASS를 보완 전체 PASS로 복사하지 않는다. QA `outcome`과 보완 `owner_review`/`owner_acceptance`는 별개이며 보완의 필수 기준이 남으면 완료되지 않는다. 기존 설정에 매핑이 없으면 품질 승인을 추정하지 않는다.

`generated_paths`는 프로젝트에서 허용한 생성물 디렉터리의 정규 상대 경로다. 기본값은 빈 목록이며 `build/`라는 이름이나 `.gitignore`만으로 예외를 만들지 않는다. 루트·상위 경로·절대 경로·glob·개인/제어 경로·심볼릭 링크는 거부한다. 허용 경로가 추적 파일 또는 선언된 입력·산출물·코드 경로를 포함해 제품 소스를 가리키면 거부하고 실행 직전에도 재확인한다. 그 밖의 소스 추가·수정·삭제와 새 심볼릭 링크 감시는 유지한다. 생성물 변경 경로와 해시는 보고서 `generated_changes`로 구분한다. 승인된 생성물 경로 내의 추적되지 않고 입력으로도 선언되지 않은 파일의 제품 의미는 자동 판별할 수 없으므로 경로 지정 자체를 신중히 해야 한다.

## 실패·중단 기록

QA 호출은 선검사 → 실행 시작 → 작업본 준비 → 기준 자료 배치 → 역할 실행 → 명령 → 결과/근거 처리 → 보고서 → 제출 → 검토 → 이슈/시도 기록 → 담당 수정 → 재시험 기준 갱신을 실패 경계로 다룬다. 시작 전에 기존 형식의 역할 실행 UUID를 예약하므로 상태 저장 후 이벤트 flush가 실패해도 이번 호출이 시작한 정확한 실행만 정리할 수 있다. 다른 호출의 열린 작업은 종료하지 않는다.

정상적인 FAIL/NOT_RUN은 기존 QA 보고서·검토·시도에 남긴다. 예상하지 못한 실패는 `.harness/qa/failures/<UUID>/report.json`, 기존 작업 원장의 `qa_failures`, `qa_execution_failed` 이벤트에 발생 단계·원인·실행 ID·종료 근거를 남긴다. 미실행 검증은 NOT_RUN이다. 이번 호출의 열린 작업·검토를 종료하고 BLOCKED로 기록한다. 검토 PASS 이후 결과 저장이 실패해도 기존 PASS 이력·파일은 보존하되 현재 완료 판정은 취소하고 재검증 필요로 표시한다. 시작 전 거부는 실제 역할 실행 실패와 구분하며 시도 상한을 소모하지 않는다. 중복 완료 호출이나 동시 호출 거부 때문에 이미 완료한 검토나 다른 실행을 중단하지 않는다.

보완 결과 처리도 동일한 실패 정리를 적용하며 독립 QA PASS와 보완 인수 완료를 구분한다. 강제 프로세스 종료/SIGKILL·전원 상실은 예외 처리로 보장할 수 없고, 저장 장치 자체가 실패하면 기록 확정을 보장할 수 없다. 이 경우 성공을 반환하지 않고 복구·재개 절차로 실제 종료 상태와 기록을 확인해야 한다. 타임아웃 연장으로 처리하지 않는다.

실패 원인 보고서는 정리 전에 생성되므로 그 안의 `execution_status`는 `UNCONFIRMED`일 수 있다. 정리 후 확정된 종료 상태는 기존 작업 원장 `qa_failures.execution_status`와 역할 실행의 `ended_at`을 원본으로 확인한다. `NOT_STARTED`는 예약 ID만 있고 실행은 생성되지 않은 경우이며 시도 상한을 소모하지 않는다. `RECORDED_ENDED`는 이번 호출이 소유한 실행의 종료가 원장에 기록됐다는 뜻이고, OS의 모든 후손 프로세스를 독립적으로 관측했다는 뜻은 아니다. 다른 프로젝트·피처·작업 유형에 속한 보완 작업은 검토·변경하지 않고 인수를 거부한다.

## 증거 계약과 프로젝트별 실행 절차

새 작업의 기준별 방법·플랫폼·환경·관찰 증거·검토 주체 연결은 [증거에 따른 완료와 재개](verification-reliability.md)를 따른다. 프로젝트 필수 정책은 신규 작업에 고정하며 과거 결과를 소급 인증하지 않는다. [검증 절차 생성·검사](verification-procedures.md)는 프로젝트 소유 명령·기능 경로를 사용하며 생성/형식 검사와 실제 실행을 구분한다.
