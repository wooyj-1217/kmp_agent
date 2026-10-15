# 버전 고정 설치·init·update

일반 제품은 원격의 **명시한 태그 또는 전체 커밋 SHA**를 설치해 사용한다. 버전 원본은 루트 [VERSION](../VERSION) 한 곳이며 초기 버전은 0.1.0이다. 브랜치·최신 HEAD를 자동 추적하지 않는다. 로컬 원본 참조는 하네스 개발용 선택 모드다. 구현은 [bootstrap.py](../bootstrap.py), 프로젝트 명령은 [cli.py](../harness/cli.py)다. Python 3.10 이상·Git·rtk가 필요하다.

## 최초 설치

도구가 없는 프로젝트에서는 Git으로 부트스트랩 코드를 특정 버전에 고정한 후 설치한다. `bootstrap.py` 한 파일만 내려받는 방식은 지원하지 않는다. 같은 버전의 `harness/` 모듈도 필요하므로 아래처럼 저장소를 확보한다. 현재 설치기는 POSIX 환경(macOS/Linux)의 Python 3.10 이상·Git·rtk가 PATH에 있어야 한다. 아래 명령으로 먼저 확인한다.

```sh
rtk --version
rtk proxy python3 --version
rtk proxy git --version
```

아래 원격·태그는 **이후 실제로 게시된 경우에만** 사용할 수 있다. 이번 작업은 원격 게시·태그 등록을 수행하지 않는다. `/path/to/product`는 기존 Git 저장소 루트로 바꾸고, 새 폴더라면 먼저 `rtk proxy git init /path/to/product`를 실행한다. `/tmp/kmp-agent-bootstrap`은 아직 없는 빈 경로를 선택한다. SSH 저장소 접근 권한이 필요하며 HTTPS 접근을 사용할 때는 clone과 --source의 URL을 함께 바꾼다.

```sh
rtk proxy git clone --no-checkout git@github.com:wooyj-1217/kmp_agent.git /tmp/kmp-agent-bootstrap
rtk proxy git -C /tmp/kmp-agent-bootstrap fetch origin refs/tags/v0.1.0
rtk proxy git -C /tmp/kmp-agent-bootstrap checkout --detach FETCH_HEAD
rtk proxy python3 /tmp/kmp-agent-bootstrap/bootstrap.py install --source git@github.com:wooyj-1217/kmp_agent.git --ref v0.1.0 --target /path/to/product
```

전체 커밋 SHA도 --ref에 지정할 수 있다. Git 인증은 기존 SSH/credential helper를 사용하고 인증값을 URL·설정에 넣지 않는다. 설치 시 태그를 커밋으로 해석해 SHA를 기록한다. 같은 source/ref의 install 재실행은 이미 고정한 정상 설치를 재사용하고 init을 반복하며, 이동한 태그를 조용히 다시 선택하지 않는다. 다른 버전은 update로 명시한다.

제품을 새로 clone해 ignored 도구 체크아웃만 없다면 같은 install 명령이 설치 정보에 고정된 실제 SHA를 다시 가져온다. 기존 직접 참조 훅의 소유권을 확인할 수 없으면 보존하고 충돌을 보고한다. 현재 데모의 기존 연결 마이그레이션은 별도 적용 단계에서 명시적으로 검토하며 이 작업에서 자동 제거하지 않는다.

설치는 대상 안의 별도 체크아웃에서 필요한 파일·구문·버전·Git 커밋을 확인하고 init까지 수행한다. init 성공은 **파일·연결 설정 준비 완료**이며 세션 적용·자동 수집 PASS가 아니다. 새 세션 및 훅 신뢰가 필요한 상태와 복구 방법을 결과 JSON에 표시한다.

## 프로젝트 명령

프로젝트 루트에서 실행한다. init은 중복 없이 연결을 보수하고, status는 설치·연결·실제 수집 근거를 읽는다.

```sh
rtk proxy python3 .kmp-agent/agent.py init
rtk proxy python3 .kmp-agent/agent.py status
rtk proxy python3 .kmp-agent/agent.py update --ref v0.1.1
rtk proxy python3 .kmp-agent/agent.py recover
```

update의 태그는 실제 게시된 버전으로 바꾸며 --ref를 생략하면 실패한다. source 생략 시 설치 정보를 재사용하고 다른 저장소는 --source로 명시한다. 원격 최신 버전을 자동 적용하는 명령은 없다. 설치/init/update 종료 코드 0은 설치·정적 연결 성공, status 종료 코드 0은 현재 버전의 실제 대상 훅 수집 VERIFIED다. 미검증·재시작·복구 대기·실패 상태의 status는 1이다.

최초 init 뒤 대상의 `/hooks`에서 두 정의를 검토·신뢰하고 새 Codex 세션에서 일반 요청을 보낸다. 업데이트의 공용 훅 명령은 같은 프로젝트 진입 파일을 사용하므로 보통 변하지 않지만 지침·스킬·시작 설정은 새 세션에서 검증한다. 파일 갱신만으로 적용 완료라 하지 않는다. 내부 테스트·모의 훅 성공과 실제 Codex 세션 PASS는 별개다.

## 파일 소유와 버전 근거

| 위치 | 소유·보존 |
| --- | --- |
| `.kmp-agent/releases/<전체 SHA>/` | 설치한 공통 도구·지침. 대상 Git 제외. 이전 정상 버전도 보존 |
| `.kmp-agent/installation.json` | 추적 가능한 project_id·설치 출처·요청 ref·실제 SHA·VERSION·상대 코드 경로·이전 설치 정보 |
| `.kmp-agent/project.json` | 안정적인 project_id·상대 project_path·선택 공통 skills 배열. 제품 고유 키 보존 |
| `.kmp-agent/agent.py` | 추적 가능한 고정 진입 파일. 설치 정보에서 실행 코드를 선택; 개인 절대 경로 없음 |
| `AGENTS.md` 관리 블록·`.codex/hooks.json` | 프로젝트 설정. 제품 지침·다른 훅 보존; 두 수집 훅만 관리 |
| `.harness/` | 프로젝트의 기존 로그·분석·실행 상태·복구 저널. Git 제외·도구 코드와 분리 |

새 대상의 설치 정보·진입 파일·설정은 Git에서 추적할 수 있고 설치 코드는 제외된다. 기존 프로젝트의 광범위한 ignore 규칙은 지우지 않으므로 필요한 설정이 이미 무시되는 경우 검토 후 해당 파일만 명시적으로 추가한다. 설치기는 staging·커밋·push를 하지 않는다.

정상 설치 코드의 실제 Git SHA와 변경 여부를 확인한다. status에 코드 참조 경로·훅 연결·대상 로그 위치를 표시한다. 새 실행 이벤트의 `harness`에는 실행 중인 도구의 VERSION·실제 commit·dirty·mode를 기록한다. 이 값은 로거/도구 런타임 관측이며 과거 세션의 모델 실행 버전을 추정한 값이 아니다. 설치 정보의 commit과 실행 코드의 commit을 별도로 확인할 수 있다.

### 프로젝트 식별·검증 범위

init은 기존 연결 설정 또는 기존 `.harness/project.json`의 project_id를 재사용한다. 기존 ID가 없으면 프로그램이 UUID를 한 번 생성한다. ID가 충돌하면 임의 선택하지 않고 실패한다. project_path는 설정 파일 위치에서 프로젝트 루트를 가리키는 `..`로 저장해 개인 절대 경로를 배포 설정에 넣지 않는다. 프로젝트 이동·버전 변경·ignored 체크아웃 복원은 ID를 바꾸지 않는다. 설치 정보·연결 설정도 함께 Git에 보존해야 새 clone에서 같은 프로젝트를 식별할 수 있다.

Logger는 프로젝트 설정에서 실행 컨텍스트를 읽으며 하위 이벤트는 run 시작 컨텍스트를 상속한다. 에이전트가 이벤트마다 project_id를 지정하지 않는다. 검증 결과·이벤트·상태 요약에는 실제 대상 ID와 `verification_scope`를 둔다. 하네스 자체 검증은 `harness_internal`, 별도 프로젝트의 연결·설치·수집 검증은 `target_project`다. 하네스에서 테스트를 실행했더라도 외부 fixture 결과는 fixture 프로젝트의 ID를 사용한다.

설정 누락·경로 불일치·ID 충돌은 `UNKNOWN`과 project_id_reason으로 표시하며 다른 프로젝트에 귀속하지 않는다. 로거는 ID 생성을 위해 프로젝트 설정을 임의로 쓰지 않는다. 과거 이벤트의 필드 누락은 그대로 읽고 상태 요약에서 legacy/UNKNOWN 그룹으로 분리한다. 과거 로그에 현재 ID를 채워 넣지 않는다. 진단·원본 근거 경로는 출처로 유지하되 실행 대상의 식별 키로 사용하지 않는다.

## 실패·중단 복구

후보 버전은 private staging에서 확인하고 정상 릴리스 경로로 옮긴다. 기존 설치·설정을 기록한 Git 제외 복구 저널을 만든 뒤 포인터·관리 설정을 갱신한다. install·반복 install·단독 init·update 모두 같은 복구 처리를 사용하며 init 실패 시 관리 파일·선택 스킬 링크를 복원한다. 네트워크/ref/구문 확인 실패는 기존 정상 설치를 바꾸지 않는다. 불완전한 private staging만 삭제하고 제품 파일·로그·정상 릴리스는 삭제하지 않는다.

중단으로 저널이 남으면 status는 RECOVERY_REQUIRED이며 init/update는 먼저 복구한다. recover 진입 파일은 현재 설치 정보가 손상돼도 저널의 이전 포인터를 읽는다. 진입 파일 자체가 없으면 게시 버전의 `bootstrap.py recover --target /path/to/product`를 사용한다. 복구 저널에는 설정 원본이 들어갈 수 있어 `.harness/`의 로컬 0600 파일로만 보존한다. 실패 후 사용자 편집 충돌이 있으면 해당 파일을 보존해 복구 방법을 확인한다.

## 로컬 개발 모드와 검증 범위

```sh
rtk proxy python3 bootstrap.py install --dev-source . --target /path/to/test-product
rtk proxy python3 -m unittest discover -s harness -p 'test_*.py'
```

개발 모드는 원본을 복사하지 않으며 WORKTREE·당시 커밋·실제 dirty를 구분한다. 기존 데모의 원본 직접 참조 연결은 이번 작업에서 제거하거나 마이그레이션하지 않는다. 설치 대상의 설정 점검·최소 갱신·해시/재시작·실제 훅 증거 판정은 [연결 검증](harness-projects.md)을 재사용한다. 하네스 훅은 등록 대상을 읽기 점검할 뿐 설치 버전이나 설정을 자동 갱신하지 않는다.

로컬 검증은 임시 Git 원본·태그/커밋·bare 저장소·별도 대상에서 설치→init→update, 반복 실행·데이터 보존·실패/중단 복구·모의 훅과 프로젝트 식별을 검사한다. 기본 테스트는 임시 데이터만 쓴다. 필요 시 테스트 실행 환경의 KMP_AGENT_TEST_REPORT로 결과 파일을 지정하면 대상 fixture에서 관측한 project_id·범위·결과를 내보낸다. 식별 누락을 검증하는 fixture 결과도 UNKNOWN과 이유를 유지한다. 실제 프로젝트 원격에는 push·tag를 하지 않는다. 새 배포 경로에서의 실제 원격 설치·Codex 세션 훅 신뢰/호출·데모 설치는 별도 검증이며 이번에는 NOT_RUN이다.
