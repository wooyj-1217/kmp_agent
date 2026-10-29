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
