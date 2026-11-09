---
name: api-and-dashboard
description: "FastAPI 백엔드(src/backend/main.py)와 Streamlit + Plotly 대화형 대시보드(src/frontend/dashboard.py, app.py)를 구현하고 확장한다. REST API 엔드포인트 추가·수정, 대시보드 KPI 카드, 차트, 지리공간 지도, 매물 탐색기, 딜 알림 탭, 거시 위험지표 탭 UI 수정 시 사용한다."
---

# API and Dashboard — FastAPI 백엔드 & Streamlit 대시보드 구현 스킬

백엔드 API(`src/backend/main.py`)와 프런트엔드 대시보드(`src/frontend/dashboard.py`)를 데이터 생산자 모듈과 경계 불일치 없이 구현한다.

## 1. 구현 전 필수 계약 확인

코드를 수정하기 전에 반드시 연결된 생산자 함수의 반환 구조를 직접 확인한다:
- KPI 카드 수정 전: `src/analytics/metrics.py`의 `compute_executive_kpis()` 반환 키 확인
- 서브마켓/ZIP 차트 수정 전: `compute_submarket_breakdown()`, `compute_zip_code_breakdown()`의 DataFrame 컬럼(`inventory_count`, `median_price`, `median_sqft_price`, `median_dom`, `price_drop_count`, `price_drop_rate`) 확인
- 거시 위험지표 탭 수정 전: `src/ingestion/distress_trends.py`의 `DATA_SOURCES`, `FETCH_STATUS`, 반환 DataFrame 컬럼(`date`, `year`, `month`, `filings`, `late_90_plus_pct`, `late_30_89_pct`) 확인

## 2. FastAPI 백엔드 작성 원칙 (`src/backend/main.py`)

1. **쿼리 파라미터와 리포지토리 인자 일치**:
   - `/api/properties`의 필터 파라미터(`cities`, `zip_codes`, `min_price`, `max_price`, `min_beds`, `min_baths`, `max_sqft_price`, `price_drop_only`, `foreclosure_only`, `source`)를 `query_properties()` 호출에 빠짐없이 전달한다.
2. **명확한 응답 구조**:
   - 목록 응답은 `{ "total": len(...), "count": ..., "items": [...] }` 또는 명시된 키 구조를 유지해 기존 API 소비자와 테스트(`tests/test_tracker.py`)가 깨지지 않게 한다.
3. **수집 트리거 엔드포인트 (`/api/ingest`)**:
   - `IngestionRequest` 스키마를 통해 `source`(`"all"`, `"realtor"`, `"foreclosure"`, `"redfin"`, `"mock"`), `submarkets`, `include_foreclosures`, `include_redfin` 옵션을 받아 `run_pipeline()`에 전달한다.

## 3. Streamlit 대시보드 작성 원칙 (`src/frontend/dashboard.py`)

1. **빈 데이터 상태(Empty State) 처리**:
   - 사용자가 선택한 사이드바 필터(도시, ZIP, 가격 범위, 침실 수, 가격 인하 전용 등) 결과가 0건일 때 Plotly 차트나 지도 함수에 빈 DataFrame을 그대로 넘겨 `KeyError`나 `ValueError`를 내지 않는다. `if df.empty:` 분기로 안내 배너를 표시한다.
2. **출처 및 데이터 신선도 투명성**:
   - 외부 공공 데이터(Fulton 카운티 퇴거 소송, CFPB 모기지 연체율, 조지아 법원 경매 공고) 차트 하단이나 헤더에는 `DATA_SOURCES`의 발행 기관·링크·주의사항(`notes`)과 `FETCH_STATUS`(`live` vs `cache`)를 명시한다. 예를 들어 퇴거 통계는 완료된 퇴거가 아닌 법원 접수 건수(Fulton 카운티 한정)임을 사용자가 오해하지 않게 표시한다.
3. **차트 가독성 및 일관성**:
   - 가격(`$`), 평당 가격(`$/sqft`), 비율(`%`), 체류 일수(`DOM`) 단위를 축 제목과 호버 툴팁(`hovertemplate`)에 분명히 표시한다.

## 4. 스모크 검증 명령

수정 후 문법 및 임포트 오류, FastAPI 라우트 동작을 즉시 확인한다:

```bash
PYTHONPATH=. ./venv/bin/python -c "
import src.frontend.dashboard as dash
from fastapi.testclient import TestClient
from src.backend.main import app
client = TestClient(app)
assert client.get('/api/health').status_code == 200
assert client.get('/api/analytics/kpis').status_code == 200
print('API & Dashboard import/smoke check passed!')
"
```

