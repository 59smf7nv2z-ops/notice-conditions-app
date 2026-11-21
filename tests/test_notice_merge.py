"""여러 글 조건 합치기(core.notice_merge)."""

from datetime import date

import pytest

from core.conditions import Contact, NoticeConditions
from core.notice_merge import MergeSource, merge


def src(url, **kw):
    base = dict(notice_id=url.rsplit("/", 1)[-1], sigungu_codes=["30140"], local_gov="대전광역시 중구")
    return MergeSource(NoticeConditions(**{**base, **kw}), [], url, f"글 {url[-1]}")


def test_official_first_and_fill_missing_from_others():
    news = src("https://news.example.com/1", source_type="NEWS", min_years=30, max_floors=2, floors_bound="LE",
               apply_start=date(2026, 3, 2), apply_end=date(2026, 3, 31),
               offmap_conditions=["또는: 노유자시설"], evidence={"min_years": "30년 이상"})
    gov = src("https://www.djjunggu.go.kr/2", source_type="OFFICIAL_NOTICE", min_years=30, max_area=500.0, area_bound="LE",
              apply_start=date(2026, 3, 25), apply_end=date(2026, 4, 17), offmap_conditions=["위원회 심사"],
              contact=Contact(inquiry="건축과 042-000-0000", documents=["신청서"]), evidence={"max_area": "500㎡ 이하"})
    m = merge([news, gov])
    n = m.notice
    assert [s.url for s in m.sources] == [gov.url, news.url]  # 공고가 먼저
    assert n.source_url == gov.url and n.source_urls == [gov.url, news.url] and n.source_type == "OFFICIAL_NOTICE"
    assert (n.apply_start, n.apply_end) == (date(2026, 3, 25), date(2026, 4, 17))  # 접수기간은 공고 것, 묶음째
    assert n.max_area == 500 and n.max_floors == 2  # 공고에 없는 층수는 뉴스에서 채움
    assert n.offmap_conditions == ["위원회 심사", "또는: 노유자시설"]
    assert n.contact.inquiry == "건축과 042-000-0000" and n.evidence["max_area"] == "[출처 1] 500㎡ 이하"
    assert "min_years" not in n.evidence  # 경과연수는 공고(출처 1) 값을 쓰고, 공고엔 인용이 없으니 뉴스 인용을 붙이지 않는다
    assert any("출처마다 다름 · 접수기간" in i for i in m.issues)
    assert m.issues[0].startswith("글 2건을 합쳤습니다") and n.reviewed is False


def test_conflicting_scale_is_reported_not_guessed():
    a = src("https://gov.go.kr/a", max_floors=3, floors_bound="LE")
    b = src("https://news.example.com/b", source_type="NEWS", max_floors=2, floors_bound="LT")
    m = merge([a, b])
    assert m.notice.max_floors == 3 and m.notice.floors_bound == "LE"
    assert any("층수: 3층 이하([출처 1] 사용) / 2층 미만([출처 2])" in i for i in m.issues)


def test_older_round_is_dropped():
    old = src("https://gov.go.kr/2025", apply_start=date(2025, 3, 1), apply_end=date(2025, 3, 31), max_area=1000.0)
    new = src("https://gov.go.kr/2026", apply_start=date(2026, 3, 1), apply_end=date(2026, 3, 31))
    m = merge([old, new])
    assert [s.url for s in m.sources] == [new.url] and m.dropped == [old]
    assert m.notice.max_area is None  # 지난 회차 값으로 채우지 않는다
    assert any("2025년 글은 올해 회차와 달라" in i for i in m.issues)


def test_use_filter_not_unioned():
    a = src("https://gov.go.kr/a", use_filter=["단독주택"])
    b = src("https://gov.go.kr/b", use_filter=["단독주택", "제1종근린생활시설"])
    m = merge([a, b])
    assert m.notice.use_filter == ["단독주택"] and any("출처마다 다름 · 용도" in i for i in m.issues)


def test_empty_raises():
    with pytest.raises(ValueError):
        merge([])
