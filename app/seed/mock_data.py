from __future__ import annotations

from dataclasses import dataclass
from datetime import date


SEED_AS_OF_DATE = date(2026, 6, 9)
SCORE_VERSION = "mock-score-rules-2026-06-09"

SCORE_COMPONENTS = [
    ("financial_stability", 20),
    ("profitability", 15),
    ("growth", 15),
    ("valuation", 10),
    ("news_attention", 10),
    ("disclosure_event", 10),
    ("liquidity", 10),
    ("momentum_volatility", 10),
]


@dataclass(frozen=True)
class MockStock:
    ticker: str
    company_name: str
    company_name_en: str
    market: str
    sector: str
    industry: str
    listing_date: date
    corp_code: str
    base_score: int
    risk_tag: str
    risk_text: str


MOCK_STOCKS = [
    MockStock(
        ticker="005930",
        company_name="삼성전자",
        company_name_en="Samsung Electronics",
        market="KOSPI",
        sector="반도체",
        industry="전자부품 제조업",
        listing_date=date(1975, 6, 11),
        corp_code="MOCK00126380",
        base_score=78,
        risk_tag="sector_cycle",
        risk_text="업종 사이클 변화에 따라 단기 지표 해석이 달라질 수 있습니다.",
    ),
    MockStock(
        ticker="000660",
        company_name="SK하이닉스",
        company_name_en="SK hynix",
        market="KOSPI",
        sector="반도체",
        industry="메모리 반도체 제조업",
        listing_date=date(1996, 12, 26),
        corp_code="MOCK00164779",
        base_score=76,
        risk_tag="high_volatility",
        risk_text="최근 가격 변동성이 확대되어 추가 확인이 필요합니다.",
    ),
    MockStock(
        ticker="035420",
        company_name="NAVER",
        company_name_en="NAVER",
        market="KOSPI",
        sector="인터넷",
        industry="포털 및 플랫폼 서비스",
        listing_date=date(2002, 10, 29),
        corp_code="MOCK00266961",
        base_score=73,
        risk_tag="platform_regulation",
        risk_text="플랫폼 관련 정책 이슈가 지표 해석에 영향을 줄 수 있습니다.",
    ),
    MockStock(
        ticker="035720",
        company_name="카카오",
        company_name_en="Kakao",
        market="KOSPI",
        sector="인터넷",
        industry="모바일 플랫폼 서비스",
        listing_date=date(2017, 7, 10),
        corp_code="MOCK00258801",
        base_score=69,
        risk_tag="earnings_variability",
        risk_text="사업 부문별 실적 편차가 있어 세부 확인이 필요합니다.",
    ),
    MockStock(
        ticker="051910",
        company_name="LG화학",
        company_name_en="LG Chem",
        market="KOSPI",
        sector="화학",
        industry="기초 화학물질 제조업",
        listing_date=date(2001, 4, 25),
        corp_code="MOCK00356370",
        base_score=71,
        risk_tag="commodity_input_cost",
        risk_text="원재료 가격 변화가 수익성 지표에 영향을 줄 수 있습니다.",
    ),
    MockStock(
        ticker="006400",
        company_name="삼성SDI",
        company_name_en="Samsung SDI",
        market="KOSPI",
        sector="2차전지",
        industry="축전지 제조업",
        listing_date=date(1979, 2, 27),
        corp_code="MOCK00126362",
        base_score=72,
        risk_tag="demand_cycle",
        risk_text="전방 수요 변화에 따라 성장 지표 확인이 필요합니다.",
    ),
    MockStock(
        ticker="068270",
        company_name="셀트리온",
        company_name_en="Celltrion",
        market="KOSPI",
        sector="바이오",
        industry="바이오 의약품 제조업",
        listing_date=date(2018, 2, 9),
        corp_code="MOCK00413046",
        base_score=70,
        risk_tag="pipeline_timing",
        risk_text="제품 승인 및 공급 일정에 따른 변동 요인이 있습니다.",
    ),
    MockStock(
        ticker="005380",
        company_name="현대차",
        company_name_en="Hyundai Motor",
        market="KOSPI",
        sector="자동차",
        industry="자동차 제조업",
        listing_date=date(1974, 6, 28),
        corp_code="MOCK00164742",
        base_score=75,
        risk_tag="fx_sensitivity",
        risk_text="환율과 지역별 판매 흐름이 실적 지표에 영향을 줄 수 있습니다.",
    ),
    MockStock(
        ticker="000270",
        company_name="기아",
        company_name_en="Kia",
        market="KOSPI",
        sector="자동차",
        industry="자동차 제조업",
        listing_date=date(1973, 7, 21),
        corp_code="MOCK00164788",
        base_score=74,
        risk_tag="inventory_cycle",
        risk_text="재고와 판매 믹스 변화에 대한 확인이 필요합니다.",
    ),
    MockStock(
        ticker="012330",
        company_name="현대모비스",
        company_name_en="Hyundai Mobis",
        market="KOSPI",
        sector="자동차부품",
        industry="자동차 부품 제조업",
        listing_date=date(1989, 9, 5),
        corp_code="MOCK00164751",
        base_score=72,
        risk_tag="margin_pressure",
        risk_text="부품 원가와 납품 구조 변화가 마진 지표에 영향을 줄 수 있습니다.",
    ),
]

