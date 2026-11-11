# 승인된 기준과 보호된 검증 작업

## 승인과 실행의 책임

개발 계획은 필수 기준을 검증 정의 JSON으로 연결한다. PRODUCT의 `development-execution.verification`은 이미 독립 검토한 계획 입력의 경로여야 한다. 구현 브리지는 그 artifact를 부모 작업에 보존하고 보호 검증을 요구한다. 구현 통합 성공·독립 QA 관찰·보완 완료 보고는 각각 유지하지만 공식 PASS 발행 권한은 주지 않는다.

`harness.verification_runner`는 명령을 실행하고 `UNTRUSTED_OBSERVATION` receipt를 쓴다. 성공은 `OBSERVED_PASS`이며 공식 PASS가 아니다. 보호 발행자는 관리자 승인 정의로 제출 커밋을 직접 실행하고 서명한다. 완료 판정기는 그 작업의 출처·대상 커밋·계획·필수 시나리오를 다시 검사한다. 원장은 캐시이며 신뢰 루트가 아니다.

## 승인 정의

검증 정의는 `schema_version: 1`, 비어 있지 않은 `plan_version`, `checks` 배열을 가진다. 각 행은 다음 필드를 가진다.

| 필드 | 의미 |
| --- | --- |
| id, criterion_id | 검증 실행 고유 ID와 승인 완료 기준 ID |
| platform | common / android / ios / web / server |
| kind | build / test / ui / api / lint / screenshot |
| required | 필수 여부 boolean |
| command | `rtk proxy`로 시작하는 argv 배열 |
| expected | 승인된 기대 결과 |
| expected_tests | 실제 결과에서 찾아야 하는 고유 시나리오 ID/이름. build/lint 외 필수 |
| results | `{path, format}` 배열. 프로젝트 상대 경로와 junit 또는 playwright 형식 |

같은 기준도 플랫폼별 check를 분리한다. Android 테스트나 API 성공으로 iOS/Web UI 검증을 충족시키지 않는다. 빌드와 lint의 exit 0은 해당 종류에만 사용한다. 테스트는 최신 결과 파일과 실제 시나리오가 필요하며 0건·전체 skip·필수 시나리오 누락/skip·결과 누락/변조·러너 미지원·타임아웃·실행 실패를 구분한다. stdout/stderr와 결과 파일 경로·SHA-256, argv·exit code·시나리오별 결과·코드 manifest/commit·정의 digest를 receipt에 기록한다.

## 관리자 보호 정책과 완료 진입점

신뢰 루트는 `/etc/kmp-agent/verification/<프로젝트 절대 경로 SHA-256>.json`이다. 후보 파일이나 환경변수로 이를 선택하지 않는다. 정책의 `schema_version: 1`, `project_root`, `issuer`, `public_key_pem`, 서로 다른 `agent_uid`/`publisher_uid`, 프로젝트 밖 `receipt_directory`/`execution_root`, `tasks` 바인딩을 확인한다. task 계약에는 `approved_commit`, 승인된 `definition`과 `definition_path`, `plan.path/sha256`, `protected_paths`, `configuration_paths`, `validation_inputs`, `criteria`, 고정 `completion_contract`/`verification_contract`를 둔다. 필수 테스트·assertion·기준 이미지·제외 설정을 빠짐없이 승인 입력으로 지정하는 것은 관리자 승인 책임이다.

`Tasks.review`의 기본 `purpose='official'`은 기존 기준/receipt 검사 후 DONE 전 보호 gate를 호출한다. 보호 정책에 등록한 task를 원장에서 삭제하거나 task 식별자/완료 설정을 바꾸는 것도 차단한다. 서명의 issuer·publisher UID·job ID·유효기간, 전체 제출 commit/tree, 승인 계획과 계약 digest, 필수 기준의 check 대응, 시나리오 결과와 원본 해시를 다시 검사한다. 대시보드의 기존 task 상세에는 공식 판정, 기준/플랫폼/종류, 미실행·차단 이유, 검증 commit/job을 투영한다.

### 구현·QA의 제한된 DONE과 공식 인증

새 `implementation_qa_v1` 작업의 위임 실행 검토와, 그 대상을 검증하도록 구성한 `qa_observation_v1` 작업의 QA 관찰 검토는 각각 `purpose='execution'`, `purpose='qa_observation'`을 사용한다. 이 두 경로는 현재 범위의 receipt와 필수 기준을 확인하고 기존 DONE 상태를 사용하되 공식 보호 PASS를 발행하지 않는다. 구현·QA 작업 구성이 없는 임의 purpose 지정은 거부한다. 원장에 purpose나 DONE만 직접 적는 것으로 유효한 제한 완료 receipt가 성립하지 않는다. 현재 코드·입력·증거 검사도 유지한다. 사람의 승인은 두 receipt 모두에서 `NOT_ESTABLISHED`이며 별도 원문 승인 근거가 필요하다.

`implementation_qa_v1`의 공식 인증에는 관리자 task 계약의 같은 `completion_semantics`, `qa_task_id`, 정확한 `qa_approval`을 요구한다. `qa_approval`은 `qa_task_id`, `agent_run_id`, `review_run_id`, `report_sha256`, `target_manifest_sha256`으로 승인한 QA basis를 고정한다. 현재 대상의 최신 QA PASS, 필수 기준, 보고서·원본 증거 해시, 대상 baseline·manifest·scope·생성물 제외 범위를 다시 검사하며 관리자 승인 basis와 같아야 한다. QA 실패·다른 대상·증거 변경·코드 추가/변경/삭제는 과거 QA를 공식 완료에 재사용할 수 없다.

보호 candidate와 서명 payload에는 관리자 승인 QA basis도 포함한다. 발행자는 후보 로컬 원장의 QA PASS 주장을 신뢰 루트로 삼지 않는다. 관리자가 정확한 QA 근거를 검토해 후보 밖 정책에 고정하는 책임과 보호 작업의 독립 실행은 유지된다. 로컬 QA PASS만으로 공식 인증하거나 사람의 제품 승인을 추정하지 않는다. 기존 계약에 새 의미를 소급 적용하지 않으며 과거 `LEGACY_UNCERTIFIED`는 그대로 비인증 이력이다.

보호 gate 거부 등으로 검토가 중단되면 호출자는 활성 review 실행에 `Tasks.fail`을 적용해 원래 실패 사유와 실행 종류를 보존하고 실행을 종료한다. 작업은 `BLOCKED`로 남으며 공식 PASS나 검토 성공 기록을 만들지 않는다. 이미 종료되었거나 다른 실행 ID에 대한 실패 처리는 거부한다. 필수 질문 응답을 기다리는 실행은 work와 review 모두 기본 실패 처리로 종료하지 않고 대기·체크포인트를 유지한다. 답변 후 재개하거나 `cancel_question_wait=True`로 대기를 명시적으로 취소한 경우에만 종료한다.

공식 보호 인증은 전체 제출 커밋을 보수적으로 무효화 범위로 사용한다. 제한된 구현 실행 receipt에 적용하는 내용 보존 commit 예외는 공식 검토·서명·보호 증거의 commit/tree/해시 검사를 완화하지 않는다. 코드가 바뀌면 영향을 추측해 과거 결과를 재사용하지 않고 재실행한다. 승인 계획·필수 테스트/assertion·기준 이미지·CI/빌드/제외 설정 변경은 기존 승인 재사용을 거부한다. 신규 테스트 파일 추가는 허용하지만 설정 추가/변경은 재승인 대상이다. 영향받는 기준을 기존 승인 담당에게 반환하고 승인 정의/정책을 갱신한 뒤 새 커밋에서 실행한다. 기존 review·실패 원본은 삭제하지 않는다.

## 실행과 운영 경계

일반 구현/QA 계정의 실행 예시는 다음과 같다. 결과는 관찰이며 공식 완료를 발행하지 않는다.

```sh
rtk proxy python3 -m harness.verification_runner --definition tools/verification.json --root /absolute/project --output verification/observed.json
rtk proxy python3 -m harness.protected_verification status --root /absolute/project --task-id TASK_ID
```

실운영에서는 후보 작업본 밖 관리자 소유의 신뢰 설치에서 판정기와 발행자를 실행해야 한다. `publish --root ... --task-id ... --private-key ... --job-id ...`는 root 발행자만 허용한다. 키와 정책·상위 디렉터리는 비신뢰 계정이 쓰거나 키를 읽을 수 없어야 한다. 후보 실행은 구현/QA와도 다른 비특권 `execution_uid/execution_gid`로 강등한다. 관리자 소유 실행 작업본에는 명시한 빌드/결과 경로만 worker 쓰기를 허용하며 Git 제어·발행 출력 경로와 심볼릭 링크는 거부한다. 서명 키는 실행 작업본 밖에 둔다. 단순 actor ID 분리나 에이전트 계정에 제공한 서명 키로는 이 경계를 보장하지 않는다.

이번 변경은 보호 서비스·OS 계정·키·관리자 정책을 배포하지 않는다. 따라서 현재 로컬 관찰 성공도 공식 완료는 `PROTECTED_AUTHORITY_UNAVAILABLE`로 차단된다. 합성 authority fixture의 실제 서명/완료 진입점 시험은 판정 계약의 회귀 증거이며 실서비스 배포 실증이 아니다. 후보 브랜치가 자신의 판정기 코드를 바꾸어 실행한 출력은 공식 판정으로 신뢰하지 않는다.

개발 위임·구현 브리지 등의 단위 테스트는 명시한 임시 프로젝트 루트의 보호 평가만 `SYNTHETIC_UNIT_TEST_ONLY` mock으로 대체할 수 있다. 이는 실행 흐름의 의존성 분리를 위한 합성 PASS이며 서명 receipt·보호 경계·인수 성공의 증거가 아니다. 공용 fixture 생성기나 실제 worker 시험에 자동 적용하지 않으며, authority 부재 시 원래 차단 사유를 유지하고 소유 실행을 종료하는 경로는 mock 없이 별도로 검증한다.

과거 원장은 읽고 원문을 보존한다. 보호 계약 없는 과거 작업은 `LEGACY_UNCERTIFIED`이며 새 공식 PASS로 승격하지 않는다. [기존 receipt 계약](verification-reliability.md), [QA 관찰/보완](qa.md), [개발 계획](templates/development-plan.md)을 함께 참조한다.

선택 HTTP 시험과 앱별 fixture는 [별도 로컬 companion](examples-separation.md)에서 명시한 하네스 source/ref로 실행한다. 해당 시험은 현재 하네스·새 설치물의 기본 입력이 아니다. server/API 증거는 그 시험의 선언 범위에만 적용하고 제품 연동·재시작 영속성·모바일 UI 검증으로 확대하지 않는다.
