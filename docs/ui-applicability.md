# UI 적용 여부 계약

`visual_required=False`는 UI 비해당 승인이나 개발 인계 권한이 아니다. 기존 문서 전용 디자인의 개발 인계 차단을 유지한다. UI 제품은 기존 HTML·시각 증거·독립 검토 계약을 사용한다.

CLI, 서버, 라이브러리, 백그라운드 서비스처럼 그래픽 인터페이스가 없는 제품은 명시 계약을 사용한다. 예:

```json
{
  "schema_version": 1,
  "status": "NOT_APPLICABLE",
  "reason": "CLI 명령만 제공하며 그래픽 인터페이스가 없다",
  "interfaces": ["cli"],
  "requirement_id": "REQ-CLI"
}
```

허용 interfaces는 `cli`, `server`, `library`, `background_service`이다. `requirement-lineage.json`의 해당 원본 요구사항 `expected.ui_applicability`는 `status`, `reason`, `interfaces`와 정확히 일치해야 한다. 선언은 원본 대신 승인으로 취급하지 않는다. PRODUCT는 기존 계보의 현재 native 인간 승인과 해당 작업 범위를 요구한다. HARNESS_TRIAL은 기존 명시 시험 승인과 제품 PASS 비주장을 유지한다. 원문이 특정 CLI 사례가 아니라 하네스 시험만 승인했다면, 해당 원문 ID에 연결한 derived item의 ui_applicability와 정확히 일치하고 그 변경에 현재 TRIAL_ONLY 결정이 있어야 한다. 이 예외는 PRODUCT에 승계하지 않는다.

`Roles.setup(..., ui_applicability="ui-applicability.json")`으로 디자인과 개발 작업 각각에 같은 계약을 등록한다. 선언·계보·모든 원본을 입력 스냅샷으로 동결한다. 개발 작업도 최초 실행 및 오케스트레이터 구성 전에 등록해야 한다. 기존 실행/오케스트레이터의 계약을 뒤늦게 약화하지 않는다. 원본, 선언 또는 스냅샷 변경은 재검토 대상으로 차단한다.

UI 비해당 디자인은 `design.md`에 인터페이스, 명령/API 입력·출력, 오류, 요구사항 대응을 작성한다. prototype HTML을 제출하지 않으며 mockup과 visual_review는 `NOT_APPLICABLE`이다. visual PASS를 만들거나 design_checks로 시각 검사를 대체하지 않는다. 단계 워크플로 등록 시 해당 디자인의 검토 도메인은 `interfaces`, `inputs_outputs`, `errors`로 각각 다른 필수 기준에 연결한다. 따라서 UI 계약을 먼저 setup하고 단계 워크플로를 구성한다.

기존 독립 역할 검토는 여전히 필수다. 실제 모델 프로세스 시작·정상 종료 근거, 현재 산출물 및 동일 계약을 연결한 독립 검토가 있어야 개발로 인계한다. 로컬 검토, 단순 independent_process 표기, 과거 PASS만으로 인계하지 않는다. 기본 오케스트레이터의 native 모델 검토가 이 근거를 기록하며 custom command는 모델 검토로 인증하지 않는다. 합성 이벤트는 모델 근거로 거부한다. 단위 시험은 프로세스 관측 경계만 mock하고 실제 모델 또는 제품 완료로 주장하지 않는다.
