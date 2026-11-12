# 설치 제품의 도구 조회와 개선 인계

이 계약은 신뢰되고 활성화된 PreToolUse 훅이 전달한 도구 호출을 분류한다. OS 샌드박스나 모든 MCP 도구의 권한 판정기가 아니다. 알려지지 않은 도구·실행 문법은 계속 거부한다.

## 셸 도구 입력

`Bash`·`exec_command`는 도구가 선택하는 기본 shell을 사용한다. 명시적 `shell` override는 `null`을 제외하고 거부하며, `cmd`와 `command`를 동시에 제공하지 않는다. 조회 명령에도 같은 검사를 적용해 검사한 명령 앞에 임의 shell 실행을 끼워 넣지 못하게 한다.

## CUA

`mcp__cua_repl__js`는 아래처럼 **하나의 직접 inventory 조회**만 지원한다. 할당·별칭·주석·복수 문장·임의 JavaScript는 지원하지 않는다. 옵션은 리터럴 JSON으로 작성한다.

```javascript
await cua.getState();
```

개별 호출로 `listApps()`, `listBrowsers()`, `listTabs()`도 지원한다. `emit`은 boolean, `listTabs`의 `browser`는 비어 있지 않은 문자열만 받는다. `completion_summary` 단독 입력은 조회 종료 보고다.

getApp은 앱을 실행할 수 있으므로 조회로 취급하지 않는다. 대상 핸들·스크린샷·DOM 조회, 탭 생성/이동, 클릭·입력·저장 및 세션 reset은 현재 지원하지 않는다. 조회가 성공해도 상호작용·변경 권한은 생기지 않는다. 임의 스크립트를 정규식으로 분류하거나 제품 구현 계약만으로 UI의 외부 변경을 승인하지 않는다. 추가 지원에는 각각의 효과를 검증할 수 있는 별도 capability 계약이 필요하다.

## 작업 발견

`mcp__codex_tui__list_threads`는 작업 목록 조회로 허용한다. create_thread나 다른 작업 관리 도구는 자동 허용하지 않는다. 목록 조회·현재 제품 루트에서 만든 새 작업은 작업 디렉터리 전환의 증거가 아니다.

## 다른 저장소의 Git 상태 확인

공통 하네스 결함 인계를 위한 외부 저장소 조회는 다음의 제한된 status 문법으로 지원한다.

```sh
rtk proxy git --no-pager --no-optional-locks -c core.fsmonitor=false -C /path/to/harness status --short --branch
```

고정된 옵션은 pager·fsmonitor 프로그램 실행과 선택적 index 쓰기를 막는다. status 옵션은 `--short`, `--branch`, `--porcelain[=v1|=v2]`, `-s`, `-b`만 허용한다. 일반 `git -C … status`는 안전한 명령을 안내하며 거부한다. 외부 diff·원격 명령·변경 명령, 임의 `-c`·다중 `-C`는 허용하지 않는다. 현재 프로젝트의 기존 Git 검사와 제품 구현·완료 게이트는 유지한다.

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
