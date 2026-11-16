"""공급자 비교: 같은 정답셋으로 키가 있는 공급자를 모두 돌려 표만 출력한다. 선택은 사람이 한다.

정답셋 위치(기본 data/eval/):
  data/eval/<공고ID>/            ← 공고 하나
      원본 파일들(.hwpx .hwp .pdf .png .jpg)
      truth.json                 ← 사람이 확정한 정답. NoticeConditions JSON 또는
                                    기존 grok 추출 형식({"결과": {...}})이면 자동 변환
      (선택) truth_business_type.txt  ← 분류 정답. 없으면 truth.json의 business_type, 그것도 없으면 APPLY_INSPECTION

legacy 정확도 계산 코드를 받지 못해 항목 일치 비교는 여기서 새로 정의했다(COMPARE_FIELDS).
받으면 그 코드로 바꾼다(scripts/legacy/README.md).

사용법 (저장소 루트):
  python scripts/compare_providers.py
  python scripts/compare_providers.py --eval-dir data/eval --include-mock
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.conditions import BusinessType, NoticeConditions  # noqa: E402
from core.llm import extractor, factory  # noqa: E402
from core.llm.base import LLMError  # noqa: E402
from core.llm.mock import MockProvider  # noqa: E402
from core.llm.preprocess import ACCEPTED, UploadedFile, to_parts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# 판정에 직접 쓰이는 항목 위주. 목록은 순서 무관 집합 비교.
COMPARE_FIELDS = [
    "min_years", "built_before_year", "max_floors", "floors_bound", "max_area", "area_bound",
    "use_filter", "structure_filter", "collective_excluded", "multi_housing_excluded",
    "apply_start", "apply_end", "selection_method",
]


def load_truth(case: Path) -> tuple[NoticeConditions, BusinessType]:
    data = json.loads((case / "truth.json").read_text(encoding="utf-8"))
    if "결과" in data:
        import migrate_notices

        n, _ = migrate_notices.convert(data, case.name)
    else:
        n = NoticeConditions.model_validate(data)
    bt_file = case / "truth_business_type.txt"
    if bt_file.exists():
        bt = BusinessType(bt_file.read_text(encoding="utf-8").strip())
    else:
        bt = n.business_type or BusinessType.APPLY_INSPECTION
    return n, bt


def file_format(case: Path) -> str:
    exts = {p.suffix.lower() for p in case.iterdir() if p.suffix.lower() in ACCEPTED}
    kinds = {".hwpx": "hwpx", ".hwp": "hwp", ".pdf": "PDF", ".png": "이미지", ".jpg": "이미지", ".jpeg": "이미지"}
    found = {kinds[e] for e in exts}
    return found.pop() if len(found) == 1 else ("혼합" if found else "없음")


def same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return set(a or []) == set(b or [])
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    return a == b


@dataclass
class Score:
    cases: int = 0
    matched: int = 0
    compared: int = 0
    by_format: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    classify_ok: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    failures: int = 0
    mismatches: list = field(default_factory=list)


def run(provider, cases: list[Path]) -> Score:
    s = Score()
    for case in cases:
        s.cases += 1
        truth, truth_bt = load_truth(case)
        files = [UploadedFile(p.name, p.read_bytes()) for p in sorted(case.iterdir()) if p.suffix.lower() in ACCEPTED]
        pre = to_parts(files)
        fmt = file_format(case)
        try:
            c = extractor.classify(pre.parts, provider, log=provider.name != "mock")
            s.input_tokens += c.usage.input_tokens
            s.output_tokens += c.usage.output_tokens
            s.retries += c.usage.retries
            s.classify_ok += c.business_type == truth_bt
            r = extractor.extract(pre.parts, provider, log=provider.name != "mock")
            s.input_tokens += r.usage.input_tokens
            s.output_tokens += r.usage.output_tokens
            s.retries += r.usage.retries
        except LLMError as e:
            s.failures += 1
            s.mismatches.append((case.name, "(실패)", str(e)))
            continue
        for f in COMPARE_FIELDS:
            ok = same(getattr(r.notice, f), getattr(truth, f))
            s.compared += 1
            s.matched += ok
            s.by_format[fmt][0] += ok
            s.by_format[fmt][1] += 1
            if not ok:
                s.mismatches.append((case.name, f, f"추출 {getattr(r.notice, f)!r} / 정답 {getattr(truth, f)!r}"))
    return s


def pct(a: int, b: int) -> str:
    return f"{a / b * 100:.1f}% ({a}/{b})" if b else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data" / "eval")
    ap.add_argument("--include-mock", action="store_true", help="파이프라인 점검용으로 샘플 공급자도 돌린다")
    ap.add_argument("--show-mismatch", action="store_true")
    args = ap.parse_args()

    cases = sorted(p for p in args.eval_dir.glob("*") if p.is_dir() and (p / "truth.json").exists()) if args.eval_dir.exists() else []
    if not cases:
        print(f"정답셋이 없습니다: {args.eval_dir}/<공고ID>/truth.json + 원본 파일 (스크립트 설명 참고)")
        return
    providers = [factory.get_provider("extract", p) for p in factory.available_providers()]
    if args.include_mock:
        providers.append(MockProvider())
    if not providers:
        print("키와 모델명이 있는 공급자가 없습니다(.env의 ANTHROPIC_API_KEY/GEMINI_API_KEY, LLM_MODEL_EXTRACT).")
        return

    formats = sorted({file_format(c) for c in cases})
    head = ["공급자·모델", "공고 수", "항목 일치율", *[f"{f} 일치율" for f in formats], "분류 정확도",
            "1건당 평균 입력 토큰", "1건당 평균 출력 토큰", "재시도", "실패"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    all_scores = []
    for p in providers:
        s = run(p, cases)
        all_scores.append((p, s))
        row = [f"{p.name}:{p.model}", s.cases, pct(s.matched, s.compared),
               *[pct(*s.by_format[f]) if f in s.by_format else "-" for f in formats],
               pct(s.classify_ok, s.cases), round(s.input_tokens / s.cases), round(s.output_tokens / s.cases), s.retries, s.failures]
        print("| " + " | ".join(str(x) for x in row) + " |")
    print("\n표만 출력합니다. 공급자 선택은 담당자가 합니다.")
    if args.show_mismatch:
        for p, s in all_scores:
            print(f"\n## {p.name}:{p.model} 불일치")
            for case, f, msg in s.mismatches:
                print(f"- {case} · {f}: {msg}")


if __name__ == "__main__":
    main()
