from core import ordinances


def test_all_inspection_ordinances_mapped_without_conflict():
    m = ordinances.load_all()
    assert len(m.ordinances) == 216
    assert m.failures == []
    assert m.conflicts == {}


def test_one_ordinance_many_codes_for_general_gu_city():
    suwon = [ordinances.get_ordinance(c) for c in ("41111", "41113", "41115", "41117")]
    assert {o.name for o in suwon} == {"경기도 수원시"}
    assert ordinances.get_ordinance("50110").name == ordinances.get_ordinance("50130").name == "제주특별자치도"


def test_loaded_values():
    jongno = ordinances.get_ordinance("11110")
    assert jongno.scale_rule_type == "DISCRETION" and not jongno.has_scale_numbers()
    assert jongno.private_only

    dangjin = ordinances.get_ordinance("44270")
    assert dangjin.scale_rule_type == "CONSTRUCTION_ACT_REF"
    assert (dangjin.min_floors, dangjin.min_floors_bound) == (3, "GE")

    gangneung = ordinances.get_ordinance("51150")
    assert (gangneung.max_floors, gangneung.floors_bound, gangneung.max_area, gangneung.area_bound) == (2, "LE", 500.0, "LT")
    assert gangneung.has_scale_numbers()

    nowon = ordinances.get_ordinance("11350")
    assert nowon.min_years is None  # 매년 정함


def test_no_ordinance_region_returns_none():
    assert ordinances.get_ordinance("43800") is None  # 충청북도 단양군: 조례 CSV에 없음


def test_external_ref_manual_override_creates_numbers():
    o = ordinances.get_ordinance("41820").model_copy()  # 경기도 가평군: 구조기준규칙 참조
    assert o.scale_rule_type == "STRUCTURE_RULE_REF" and not o.has_scale_numbers()
    o.manual_override = {"max_floors": 2, "floors_bound": "LE", "max_area": 500, "area_bound": "LT"}
    assert o.has_scale_numbers()
    assert o.effective_scale()["max_area"] == 500
