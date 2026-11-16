"""data/ref 법정동코드 파일 점검.

단계 2의 core/regions.py가 이 파일을 쓴다. 파일이 바뀌었을 때(최신본 교체 등)
형식·개편 반영 여부가 달라지면 여기서 먼저 깨지게 한다.
"""

import csv
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BJDONG = ROOT / "data" / "ref" / "bjdong_codes_20260929.csv"


@lru_cache(maxsize=1)
def codes() -> dict[str, tuple[str, str]]:
    # 행정표준코드관리시스템 내려받기 파일: 쉼표 구분, cp949
    text = BJDONG.read_bytes().decode("cp949")
    rows = list(csv.reader(text.splitlines()))
    assert rows[0] == ["법정동코드", "법정동명", "폐지여부"]
    return {r[0]: (r[1], r[2]) for r in rows[1:]}


def test_codes_are_10_digits_and_status_known():
    c = codes()
    assert len(c) > 50_000
    assert all(len(k) == 10 and k.isdigit() for k in c)
    assert {s for _, s in c.values()} == {"존재", "폐지"}


def test_cheongun_dong():
    assert codes()["1111010100"] == ("서울특별시 종로구 청운동", "존재")


def test_incheon_reorganization_2026_07_01():
    c = codes()
    for code, name in [
        ("2812500000", "인천광역시 제물포구"),
        ("2815500000", "인천광역시 영종구"),
        ("2827500000", "인천광역시 서해구"),
        ("2829000000", "인천광역시 검단구"),
    ]:
        assert c[code] == (name, "존재"), f"{name}이 없으면 데이터 파일이 오래된 것"
    for code in ("2811000000", "2814000000", "2826000000"):  # 중구, 동구, 서구
        assert c[code][1] == "폐지"


def test_gwangju_jeonnam_merger():
    c = codes()
    assert c["1200000000"] == ("전남광주통합특별시", "존재")
    assert c["1221000000"] == ("전남광주통합특별시 동구", "존재")
    assert c["2911000000"] == ("광주광역시 동구", "폐지")
