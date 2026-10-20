'use strict';
// P-004 / CR-003 / TASK-STAR-RETURN. ISSUE-003: 기존 샘플 교체 처리 뒤 과거 선택 안내만 제거한다.
// favorites-cr003.js 뒤에 defer로 실행한다. 저장·정렬·메모 데이터·기존 이벤트는 변경하지 않는다.
for (const id of ['reset', 'emptyList']) {
  document.getElementById(id).addEventListener('click', () => {
    document.getElementById('listStatus').textContent = '';
  });
}
