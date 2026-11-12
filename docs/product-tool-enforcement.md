# 제품 기술 계약의 도구·종료 검사

제품의 원본 기술 결정을 구현 전에 확인한다. ‘이전 구현을 참고하지 말라’는 요청은 이전 코드·디자인·브랜치 작업물을 제품 입력으로 쓰지 말라는 범위이며, 명시된 기술 요구를 폐기하거나 새 스택을 임의 선택할 권한이 아니다. 기존 기술 요구의 출처를 확인할 수 없으면 기획 초안·조사는 진행하되 구현 기술을 결정하는 작업은 보류한다.

## 제품별 원본 계약

공통 하네스는 모든 제품을 특정 스택으로 바꾸지 않는다. 제품이 KMP 공통 로직·Compose 공통 화면·Kotlin/Ktor 서버를 요구했다면 그 내용을 기존 `requirement-lineage.json`의 authoritative requirement와 `development_constraints`에 포함한다. 일반 기능 기획 승인이나 에이전트의 CONFIRMED 표기는 기술 변경 승인이 아니다. 현재 원본·전체 기술 정책과 결합된 native 인간 승인 및 독립 requirements QA가 필요하다.

공유 Compose UI는 `ui_sharing: shared`, 공통 소스의 `ui_owners: kmp`, 실제 Android·iOS·Web 진입 파일·실행 명령으로 구성한다. `source_rules`에는 실제 공통 Composable 호출과 Ktor 서버 의존·진입점 등 제품 구조를 검사할 패턴을 명시한다. 기술 변경을 금지한 제품에서는 Python 서버 파일이나 플랫폼별 WebView UI 등 대체 경로도 금지 패턴으로 표현한다. 모든 소스의 의미를 하네스가 자동 추론한다는 뜻은 아니다. [개발 제약](development-constraints.md)의 스키마와 검사 범위를 따른다.

## 착수 순서

1. 제품의 기존 원본 요구·기술 제약을 확인하고 플랫폼·공유 UI·서버 기술·DB·소유 경로·명령의 미결정을 해소한다.
2. 전체 계획과 현재 native 세션을 연결한다. 기획·디자인·개발 계획의 필요한 독립 검토와 원본 일치 검사를 수행한다.
3. 기존 `configure-stage`로 승인 기술 제약을 동결하고, 대상 코드 경로·입력 버전·담당 계획을 설정한다.
4. `ready`와 `begin`을 통과한 정확한 PRODUCT 구현 실행에서만 소스를 작성한다. TODO 등록·별도 Markdown 체크리스트·테스트 숫자는 착수 허가가 아니다.
5. 제출·검토는 동일 코드 상태와 모든 선택 플랫폼의 실제 명령 증거를 사용한다. 미실행·구식 검증·미완료 원장을 제품 완료나 정식 릴리스 허가로 표시하지 않는다. 미완료 작업의 저장·개발 브랜치 공유는 별도 경로다.

설치 진입점의 `task --operation`은 기존 API의 `register-execution-plan`, `revise-execution-plan`, `configure-execution-policy`, `bind-execution-session`, `configure-task-plan`, `open-question`, `answer-question`도 제공한다. 최초 정책 설정→전체 계획 등록→담당 상세 계획→단계 계약→ready/begin 순서를 따른다. 다음 실행은 기존 정책을 바꾸지 않고 세션을 바인딩한다. 추가 단계는 [전체 계획 확장](execution-policy.md#이미-시작한-전체-계획에-단계-추가)으로 연결한 뒤 상세 계획을 등록한다. JSON 인자 파일은 `docs/guard-inputs/` 아래 준비할 수 있다. `.harness` 원장이나 설치·훅 파일을 raw 편집해 상태를 만들어 넣지 않는다. 새 revise CLI는 v0.4.6에서 추가했으며 기존 v0.4.5 설치본에 소급 적용되지 않는다.

## 소스·원장이 없는 새 프로젝트의 준비

빈 작업 원장은 구현 허가가 없다는 뜻이지 기획·준비를 중단해야 한다는 뜻이 아니다. 현재 프로젝트의 원본 요구·설정과 설치 지침을 읽고, 새 전체 계획·기획/문서 작업과 필요한 계약을 공식 task 진입점으로 준비한다. 필요한 플랫폼·정책·기술 결정이 없으면 구체적인 질문과 영향 범위를 제시하며, 미응답을 승인으로 만들지 않는다. 이전 구현을 참조하지 않는 요청도 현재 설치 지침의 KMP 등 기술 요구를 폐기하지 않는다.

[설치용 작업 명령](task-management.md#cli와-역할-실행-범위)의 도움말과 `docs/guard-inputs/` JSON 객체를 사용한다. 정상 원문 조회·도움말에 구현 작업이나 UI 검증 계약을 요구하지 않는다. 압축 원문 복원·조회 오류가 나면 막힌 도구/명령과 다음 복구 동작을 특정하며, ‘소스 없음·원장 비어 있음’만으로 전체 준비를 중단하지 않는다. 실제 제품 소스는 기존 승인 계약·단계 검토와 ready/begin을 통과한 뒤 작성한다.

## 설치된 도구 검사

이 변경을 포함한 버전을 명시적으로 설치/update하고 init하면 기존 수신·Stop 수집 훅을 보존하면서 PreToolUse와 별도 Stop guard를 추가한다. 다른 제품 훅은 보존하며 같은 guard 중복이나 PreToolUse 범위 축소는 거절한다. 설치 파일 갱신은 신뢰·활성화 성공이 아니다. `/hooks` 검토·신뢰, 새 세션, 실제 허용/거부 요청을 별도로 확인한다.

PreToolUse는 동작을 먼저 분류한다. 제품 소스 변경에는 기존 Tasks의 native 세션 바인딩·전체/담당 계획·활성 구현·단계 검토·동결 기술 계약·기준 버전·코드 소유 경로를 확인한다. 읽기·작업 저장·개발 브랜치 공유에는 제품 원장을 요구하지 않는다. 이 검사 자체는 승인 상태를 만들지 않는다.

- 일반 읽기와 선택된 프로젝트 진입점의 메타데이터 API는 준비 단계에서 허용한다. `docs/guard-inputs/`의 JSON 객체 인자 초안은 구현 경로와 겹치지 않아야 한다. 다른 문서·lineage patch는 정확한 경로를 사전에 동결한 활성 documentation 작업 또는 해당 경로를 소유한 활성 구현 작업을 요구한다.
- 설치된 공식 `.kmp-agent/agent.py update --ref <태그|40자리 SHA>`는 [관리 업데이트 계약](guard-capabilities.md#설치본의-명시적-관리-업데이트)으로 분류한다. 기존 설치 source와 검증된 launcher/runtime을 사용하며, 제품 작업의 차단·미완료 원장을 완료로 바꾸지 않는다. 임의 source·개발 모드·target 덮어쓰기·직접 bootstrap/clone 실행은 이 허용에 포함되지 않는다.
- Git 읽기 명령도 프로그램 실행·파일 출력 옵션을 검사하며, `--upload-pack`/`-u`, `--filters`, `--output`·`--ext-diff`·`--textconv`와 그 긴 옵션 축약형은 거절한다. `ls-remote`의 명시적 remote-helper(`scheme::`)와 허용 목록에 없는 URL scheme도 거절한다.
- 지원하는 apply_patch 입력은 쓰기 전에 현재 파일로 미리 대조한다. 제어 파일·프로젝트 탈출·symlink·코드 소유 범위 밖 수정과 승인된 금지 패턴은 명시적 deny로 거절한다. 불명확한 patch 형식은 허용으로 추정하지 않는다.
- 직접 인터프리터·복합 셸·알 수 없는 로컬 도구는 거절한다. 읽기 명령 이름을 가진 임의 실행 경로도 허용하지 않는다. 모델은 검사 실패를 우회할 새 실행 경로를 찾지 말고 입력·계약을 보완해야 한다.
- 제품 명령은 `.kmp-agent/agent.py command`와 승인된 `target_commands` argv를 사용한다. 동일 검사를 Logger.command 내부에도 적용해 wrapper 인자로 임의 코드를 넣지 못하게 한다. 필요한 준비·빌드·영역별 시험·통합 명령은 원본 계약에 명시한다. 설치된 제품의 위임 설정은 자식 생성 전에 모든 영역·통합 명령의 포함 여부와 native codex adapter를 검사한다. 명령 wrapper는 명시한 작업을 검사하므로 부모·여러 자식의 동시 활성 상태도 처리한다. 작업을 지정하지 않는 raw patch는 활성 구현이 하나여야 한다.
- 설치된 역할 실행의 임의 `--worker`와 프로젝트 `--target` 덮어쓰기는 허용하지 않는다.
- QA·개발 위임 adapter도 설정 시점과 실행 직전에 native codex 및 승인 argv를 검사한다. 기술 계약 이전의 문서 QA는 명령 없는 모델 검토를 허용하고, 임의 Python 등 외부 명령은 허용하지 않는다. 설치된 QA·위임 API에 시험용 worker를 주입하지 않는다.
- Git add/commit과 개발 브랜치 push는 작업 저장·공유이며 제품 인증과 분리한다. 릴리스·보호 ref는 이 공유 경로로 허용하지 않는다. 공식 product finish는 기본 `completed`일 때 기존 DONE·현재 코드/기술 계약·검토·완료 조건을 요구한다.
- Stop은 대화 종료를 허용하며 제품 완료를 선언하지 않는다. 실행 종료의 `blocked`·`handoff`·`user_stopped`·`paused` 사유와 결과 기록, 문서 범위 등록·독립 QA·구조화 UI fixture 계약은 [도구 경계](guard-capabilities.md)에 따른다.

## 보장 범위와 제한

PreToolUse 거부는 공식 Codex [훅 문서](https://learn.chatgpt.com/docs/hooks)의 명시적 deny 형식으로 반환한다. 정상 Stop은 빈 응답으로 허용하며 제품 완료를 요구하는 continuation을 반환하지 않는다. 단순 예외·timeout·잘못된 응답은 runtime에 따라 fail-open일 수 있으므로 guard 내부의 판정·입력 오류는 가능한 한 명시적 거부 응답으로 변환한다.

이 기능은 지원되고 신뢰·활성화된 로컬 도구 경로의 guardrail이다. OS sandbox나 서버의 branch protection이 아니다. 훅 비활성화·미신뢰·import 실패·runtime timeout·특수 도구의 훅 제외·이미 실행 중인 write_stdin 세션·Codex 밖의 셸이나 사용자의 직접 파일 변경까지 막는다고 주장하지 않는다. 필요한 조직은 runtime의 managed hooks 및 별도 OS/서버 정책을 함께 설정해야 한다. 일반 설치기가 관리자 정책을 임의 변경하지 않는다.

알 수 없는 도구는 차단하므로 자동화 클라이언트가 지원하는 도구·argv를 연결하지 않았다면 일부 워크플로가 진행되지 않을 수 있다. 임의 셸 통과로 해결하지 않고 필요한 경로를 검토·시험한 뒤 명시적으로 지원한다. 관리되지 않는 과거 dev-source 직접 연결에는 이 guard 설치를 소급 가정하지 않는다.

단위 fixture의 승인·lifecycle 모의는 구조 검사일 뿐 실제 인간 승인이나 제품 인수가 아니다. 실제 Codex 세션에서 guard 거부가 관측됐는지, 설치·trust·재시작이 확인됐는지, 모든 제품 플랫폼이 검증됐는지는 각각 별도로 보고한다.
