# 설치 제품의 도구 조회와 개선 인계

이 계약은 신뢰되고 활성화된 PreToolUse 훅이 전달한 도구 호출을 분류한다. OS 샌드박스나 모든 MCP 도구의 권한 판정기가 아니다. 알려지지 않은 도구·실행 문법은 계속 거부한다.

## 셸 도구 입력

`Bash`·`exec_command`는 도구가 선택하는 기본 shell을 사용한다. 명시적 `shell` override는 `null`을 제외하고 거부하며, `cmd`와 `command`를 동시에 제공하지 않는다. `functions.exec_command`도 같은 입력 계약으로 검사한다. 따옴표 상태를 구분하는 제한된 셸 검사로 single-quoted 정규식의 `|`, `$`, `;`는 인자로 허용하고 실제 연산자·치환·리다이렉션·복수 줄은 거부한다. 조회 명령에도 같은 검사를 적용해 검사한 명령 앞에 임의 shell 실행을 끼워 넣지 못하게 한다.

## CUA

`mcp__cua_repl__js`는 아래처럼 **하나의 직접 inventory 조회**만 지원한다. 할당·별칭·주석·복수 문장·임의 JavaScript는 지원하지 않는다. 옵션은 리터럴 JSON으로 작성한다.

```javascript
await cua.getState();
```

개별 호출로 `listApps()`, `listBrowsers()`, `listTabs()`도 지원한다. `emit`은 boolean, `listTabs`의 `browser`는 비어 있지 않은 문자열만 받는다. `completion_summary` 단독 입력은 조회 종료 보고다.

이 CUA REPL 경로에서는 getApp을 앱 실행 가능 동작으로 분류해 조회로 허용하지 않는다. 대상 핸들·스크린샷·DOM 조회, 탭 생성/이동, 클릭·입력·저장 및 세션 reset도 지원하지 않는다. 별도 구조화 도구의 검증 계약은 아래 독립 QA·UI 검증 절을 따른다. 조회가 성공해도 상호작용·변경 권한은 생기지 않는다. 임의 스크립트를 정규식으로 분류하거나 제품 구현 계약만으로 UI의 외부 변경을 승인하지 않는다. CUA REPL 자체를 확장하려면 각 동작의 효과를 검증할 수 있는 별도 계약과 런타임 시험이 필요하다.

## 작업 발견

`mcp__codex_tui__list_threads`는 작업 목록 조회로 허용한다. create_thread나 다른 작업 관리 도구는 자동 허용하지 않는다. 목록 조회·현재 제품 루트에서 만든 새 작업은 작업 디렉터리 전환의 증거가 아니다.

## 다른 저장소의 Git 상태 확인

공통 하네스 결함 인계를 위한 외부 저장소 조회는 다음의 제한된 status 문법으로 지원한다.

```sh
rtk proxy git --no-pager --no-optional-locks -c core.fsmonitor=false -C /path/to/harness status --short --branch
```

고정된 옵션은 pager·fsmonitor 프로그램 실행과 선택적 index 쓰기를 막는다. status 옵션은 `--short`, `--branch`, `--porcelain[=v1|=v2]`, `-s`, `-b`만 허용한다. 일반 `git -C … status`는 안전한 명령을 안내하며 거부한다. 외부 diff·원격 명령·변경 명령, 임의 `-c`·다중 `-C`는 허용하지 않는다. 현재 프로젝트의 소스 변경·공식 완료 게이트는 유지한다.

이 경로는 외부 저장소 수정 권한을 부여하지 않는다. [개선 PR 정책](harness-defect-pr.md)에 따른 수정은 하네스 루트의 별도 실행에서 기존 변경을 보존한 격리 브랜치로 수행한다. 설치 사본·control 파일·훅 신뢰 설정을 수정해 차단을 우회하지 않는다. 준비 계약 누락은 [단계 준비 진단](stage-readiness.md)에 따라 현재 원장에 연결한다.

검증은 제품 데이터 없는 합성 fixture의 guard 반환값과 임시 Git 실행을 구분한다. 실제 Codex의 훅 신뢰·도구 이름 전달·CUA 조회 성공·UI 상호작용 검증은 별도이며 단위 테스트로 대체하지 않는다.

## 설치본의 명시적 관리 업데이트

v0.4.3부터 설치 모드의 다음 공식 진입점만 제품 구현 작업과 분리된 관리 경로로 지원한다. `rtk proxy`로 감쌀 수 있다.

```sh
rtk proxy python3 .kmp-agent/agent.py update --ref <게시된-태그-또는-40자리-커밋-SHA>
```

Python 3 환경의 `python` 실행 이름도 같은 공식 진입점·인자 계약으로 분류한다. 예시와 권장 명령은 `python3`를 사용하며 Python 3.10 이상이라는 실행 요건은 같다.

기존 설치 정보의 source를 재사용한다. `--source`는 기존 값과 같아도 허용하지 않으며, `--target`·개발 모드·임의 bootstrap·clone 실행을 이 경로로 허용하지 않는다. branch·최신 HEAD를 자동 선택하지 않는다. `init`·`recover`는 여전히 사용자 터미널의 관리 명령이다.

guard와 CLI가 같은 관리 계약으로 공식 launcher 원문, 선택된 runtime 경로·커밋 SHA·Git clean 상태와 실제 CLI argv를 확인한다. launcher나 설치 코드가 바뀌었거나 출처가 불일치하면 지원 경로로 인정하지 않는다. 명령 이름만 같거나 CLI 인자 파싱 결과가 비슷하다는 이유로 임의 실행을 허용하지 않는다. 이 관리 경로는 제품 소스·원장·훅 신뢰를 raw 수정하는 권한이 아니다.

v0.4.2의 이미 설치된 guard에는 이 지원이 소급 반영되지 않는다. v0.4.2에서 v0.4.3으로 처음 전환할 때는 [설치 안내](installation.md#기존-guard에서-v043으로-첫-전환)에 따라 **사용자 터미널에서 새 v0.4.3 bootstrap**을 실행한다. v0.4.3 설치 후의 다음 명시적 update부터 위 관리 경로를 사용할 수 있다. 훅 비활성화·설치 사본 직접 편집으로 첫 전환을 우회하지 않는다.

합성 설치·guard/CLI 검사와 실제 Codex 세션의 훅 신뢰·도구 전달·실제 제품 업데이트는 별도 검증 범위다. 설치 성공을 제품 작업 재개나 원래 결함 해결 PASS로 대신하지 않는다.

## 저장·공유·대화 종료와 제품 인증

- `git add`와 명시적 메시지(`-m`/`--message`, `-F`/`--file`)를 지정한 `git commit`은 구현 착수와 분리한 작업 저장이다. 저장용으로 지원한 옵션만 허용하며 hook 우회·amend·대화형 add는 거부한다.
- `git push --no-follow-tags [-u] <remote-name> <branch>` 또는 `HEAD:refs/heads/<branch>`는 미완료 작업 공유용이다. 태그·삭제·force·mirror·기본 refspec·main/master/release/production 등 보호 대상은 거부한다. `--no-follow-tags`로 Git 설정의 자동 태그 게시도 억제한다. 서버의 branch protection과 CI 배포 정책은 별도다. 공유 허용을 릴리스 승인으로 사용하지 않는다.
- Stop은 대화 턴 종료이며 원장·제품 완료를 검사하지 않는다. task DONE이나 검토 PASS를 만들지 않는다.
- `finish --end-reason completed`(기본값)는 기존 제품 완료 계약을 검사한다. `blocked`, `handoff`, `user_stopped`, `paused`는 실행만 종료한다. 수행자는 `--result`에 이유·남은 작업·재개 지점을 기록해야 하며 하네스는 그 자유문 내용의 타당성을 인증하지 않는다. 작업·검토 상태는 바꾸지 않는다. 이것은 사용자 중단 승인을 자동 인증하는 기능이 아니다.
- 원장 JSON이 손상돼도 읽기·저장·브랜치 공유·Stop은 가능하다. 쓰기·검증·인증에는 정상 원장이 필요하다. `git remote -v`와 `sed -n '시작,끝p' 파일`의 제한된 조회도 지원한다. sed의 임의 프로그램·write/execute·`-i`/`-f`는 허용하지 않는다.

## 별도 검토와 문서 작업

실제 `collaboration.spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`, `interrupt_agent` 이름과 기존 bare 이름을 지원한다. 호출 자체는 제품 쓰기 권한이 아니다. 자식 실행도 해당 소스·세션 계약을 충족해야 한다. 임의 orchestration JavaScript인 `functions.exec`/`exec`는 읽기로 취급하지 않는다. 중첩 호출별 훅 전달을 입증하지 않은 실행기를 포괄 허용하지 않는다.

Markdown 또는 `docs/*.json` 확장자만으로 patch를 허용하지 않는다. 준비 인자 JSON 객체는 역할이 고정된 `docs/guard-inputs/` 아래에서 작성한다. 이 namespace는 설정·명령 인자 초안용이며 제품 실행 자원으로 사용하지 않는다. 다른 문서는 TODO/READY에서 `task --operation configure-documents`로 `task_id`, 정확한 `paths`, `reason`을 한 번 등록한다. 세션 계획에 포함된 IN_PROGRESS `execution_scope: documentation` 작업의 열린 work 실행에서 그 경로만 편집한다. JSON 인자 초안과 문서 경로가 어느 등록 작업의 `code_paths`와 겹쳐도 준비·문서 예외를 적용하지 않는다. lineage 초안 수정도 같은 범위 계약을 사용하며 실제 승인 검사는 기존 생명주기에 남는다.

## 독립 QA·UI 검증

`command`는 활성 구현 외에도 native verification review 또는 독립 verification 작업을 지원한다. 같은 세션·계획 소속·검증 역할·구현자와 다른 actor·동결 대상 상태·원본 `target_commands`와 일치하는 argv를 요구한다. QA는 기존 `qa_config`의 명령·target manifest를 함께 검사한다. 완료 뒤 재검증은 native certification review 또는 새 QA 작업으로 실행하며 DONE 이력을 직접 수정하지 않는다.

UI 검증에는 기존 verification 계약을 갖춘 별도 PRODUCT verification 작업에서 다음 JSON artifact를 `task --operation configure-verification-capabilities`의 `task_id`, `definition` 경로로 한 번 동결한다. `target_task_id`는 대상 구현 작업이다. 아래 도구 이름은 설명용 fixture이며 실제 연결된 runtime의 구조화 도구와 입력 스키마로 교체해야 한다.

```json
{
  "version": 1,
  "target_task_id": "DEV",
  "tools": [{
    "tool_name": "mcp__ui__screenshot",
    "target": {"app_id": "test-app"},
    "input": {"app_id": "test-app"}
  }]
}
```

지원하는 MCP 도구의 마지막 이름은 `screenshot`, `get_screenshot`, `read_screen`, `click`, `double_click`, `type_text`, `keypress`, `scroll`로 제한한다. 일반 파일 쓰기·애플리케이션 변경 도구는 UI fixture로 등록할 수 없다. `path`, `output_path`, `file_path`, `filename` 필드는 `verification/` 아래 상대 출력 경로만 받으며 절대 경로와 `..`를 거부한다. 실행 허용 직전에는 경로를 resolve해 프로젝트의 `verification/` 안에 남는지 확인하고 출력 파일과 프로젝트 내부 부모 경로의 symlink를 거부한다. 검사 이후 외부 런타임이 쓰기 전 경로가 바뀌는 경쟁 조건까지 차단하는 OS 파일 접근 격리는 아니다.

허용된 실제 MCP 도구 이름·target ID·입력 JSON 전체가 정확히 같을 때만 실행한다. 클릭 좌표·입력 문자열도 fixture에 동결하며 등록하지 않은 입력·대상은 거부한다. 등록 동작의 제품상 안전성과 외부 영향은 프로젝트가 검토해야 한다. 대상 코드·fixture 원문·snapshot이 바뀌거나 세션·actor가 다르면 거부한다. JS·셸·평가 실행 도구는 등록할 수 없으며 CUA REPL은 위 inventory 조회만 지원한다. 따라서 JS REPL만 제공하는 UI 환경은 아직 사용할 수 없다. 합성 구조화 도구 시험 PASS와 실제 UI runtime의 screenshot/click 연결 시험은 별도다.
