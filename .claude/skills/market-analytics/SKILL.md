---
name: market-analytics
description: "SQLite/SQLAlchemy 모델(src/database/)과 DuckDB/Pandas OLAP 분석 엔진(src/analytics/metrics.py)을 사용해 부동산 KPI, 서브마켓·ZIP별 집계, 분위수(Quantile), DOM 코호트, 임대 수익률, 거시 위험지표 추세를 계산한다. 새로운 통계 지표 추가, DB 스키마·리포지토리 쿼리 수정, DuckDB 고급 분석 쿼리 작성 시 사용한다. 웹 스크래핑 수집 자체는 data-ingestion 스킬을 사용한다."
---

# Market Analytics — 데이터베이스 및 DuckDB/Pandas OLAP 분석 스킬

`src/database/`와 `src/analytics/metrics.py`를 통해 정확하고 직렬화 안전한 부동산 시장 지표를 계산한다.

## 1. 데이터베이스 및 리포지토리 원칙 (`src/database/`)

1. **세션 관리 일관성**:
   - 일반 스크립트·파이프라인·분석 모듈에서는 `with get_session() as session:` 컨텍스트 매니저를 사용한다.
   - FastAPI 엔드포인트에서는 `Depends(get_db)` 제너레이터를 사용한다.
2. **`to_dict()` 직렬화 계약**:
   - `Property`, `PriceHistory`, `AlertRule`, `AlertLog`, `RentalListing` 모델에 컬럼을 추가할 때는 반드시 해당 모델의 `to_dict()` 메서드에도 필드를 추가한다. `get_properties_dataframe()`과 FastAPI 응답이 모두 `to_dict()`에 의존하기 때문이다.

## 2. KPI 및 집계 함수 작성 원칙 (`src/analytics/metrics.py`)

1. **빈 DataFrame 방어 필수**:
   - 모든 분석 함수(`compute_executive_kpis`, `compute_submarket_breakdown`, `compute_zip_code_breakdown` 등)는 첫 줄에서 `if df.empty:`를 검사하고, 소비자(API·대시보드)가 기대하는 키를 모두 포함한 기본값 딕셔너리 또는 빈 `pd.DataFrame()`을 반환한다.
   - `compute_executive_kpis`의 필수 반환 키 계약:
     - `total_inventory` (`int`)
     - `median_price` (`float`)
     - `median_sqft_price` (`float`)
     - `median_dom` (`int`)
     - `price_drop_count` (`int`)
     - `price_drop_pct_inventory` (`float`)
     - `avg_price_drop_rate` (`float`)
     - `sub_220_count` (`int`)
     - `foreclosure_count` (`int`)
2. **결측치 및 0 나눗셈 방지**:
   - `price_per_sqft` 집계 시 `.dropna()`를 먼저 적용한 뒤 중앙값을 구한다.
   - 비율 계산 시 분모(`total_inventory`, `inventory_count`)가 `0`인지 확인한다.
3. **DuckDB OLAP 쿼리 (`compute_duckdb_advanced_analytics`)**:
   - 분위수(`QUANTILE_CONT`)나 DOM 코호트(`CASE WHEN days_on_market ...`) 분석은 DuckDB 인메모리 엔진에서 수행한다.
   - 결과에 포함된 `NaN`이나 `numpy` 스칼라 타입은 `.fillna(0)` 및 Python 기본 타입(`float`, `int`, `to_dict(orient="records")`)으로 변환해 JSON 직렬화 오류를 예방한다.

## 3. 검증 명령

분석 로직을 수정한 뒤에는 아래 명령으로 빈 입력과 실제 DB 입력 모두에서 예외 없이 동작하는지 확인한다:

```bash
PYTHONPATH=. ./venv/bin/python -c "
import pandas as pd
from src.analytics.metrics import get_properties_dataframe, compute_executive_kpis, compute_duckdb_advanced_analytics
print('Empty KPI:', compute_executive_kpis(pd.DataFrame()))
df = get_properties_dataframe()
print('Live KPI:', compute_executive_kpis(df))
print('DuckDB keys:', list(compute_duckdb_advanced_analytics(df).keys()))
"
```

