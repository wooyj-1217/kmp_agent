# 설치 제품의 도구 조회와 개선 인계

이 계약은 신뢰되고 활성화된 PreToolUse 훅이 전달한 도구 호출을 분류한다. OS 샌드박스나 모든 MCP 도구의 권한 판정기가 아니다. 알려지지 않은 도구·실행 문법은 계속 거부한다.

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
