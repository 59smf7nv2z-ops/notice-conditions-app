"""조례 동기화 운영자 스크립트 (단계 7-2). 앱에서 부르지 않는다.

법제처 Open API는 신청 때 등록한 IP에서만 동작한다 → 등록된 PC에서 수동으로 실행한다. .env의 LAW_API_OC 필요.

1) 변경 확인 → 제안·diff 리포트 만들기(원본은 바꾸지 않음)
   python scripts/sync_ordinances.py check
   → data/ordinances/sync/<날짜>/proposal.csv, diff.md, law_ids.csv

2) 사람이 diff.md를 검토한 뒤 승인
   python scripts/sync_ordinances.py apply data/ordinances/sync/<날짜>/proposal.csv --yes
   → ordinances_raw.csv 갱신 + 분류 초안 재생성

변경 조문의 조건 초안은 계획의 LLM 대신 기존 규칙 분류기(scripts/classify_ordinances.py)로 만든다:
조례 216건으로 검증된 규칙이고 비용·변동이 없다. 규칙이 못 읽는 조문은 review_needed=Y로 남는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

import classify_ordinances  # noqa: E402
from core import ordinance_sync as sync  # noqa: E402

ORD_DIR = ROOT / "data" / "ordinances"
RAW = ORD_DIR / "ordinances_raw.csv"
RAW_FIELDS = ["지자체", "조례명", "시행일", "조문"]
QUERY = "건축물관리 조례"


def oc_value() -> str:
    load_dotenv(ROOT / ".env")
    oc = (os.environ.get("LAW_API_OC") or "").strip()
    if not oc:
        sys.exit(".env에 LAW_API_OC가 없습니다(법제처 Open API 신청 때 받은 인증값).")
    return oc


def check(out_dir: Path, query: str) -> None:
    oc = oc_value()
    raw = sync.read_csv(RAW)
    listed = sync.list_ordinances(oc, query)
    print(f"법제처 목록 {len(listed)}건 받음")
    cs = sync.detect_changes(raw, listed)
    print(f"변경 {len(cs.changes)}건, 그대로 {cs.unchanged}건, 목록에서 못 찾음 {len(cs.missing)}건")

    draft = {(r["지자체"], r["ordinance_name"]): r for r in classify_ordinances.classify_file(RAW) if r["row_role"] == "점검대상"}
    proposal, lines = [], [f"# 조례 동기화 diff ({date.today().isoformat()})", "", "사람이 검토한 뒤 `apply`로 반영합니다.", ""]
    ids = []
    for ch in cs.changes:
        ids.append({"지자체": ch.jurisdiction, "조례명": ch.name, "자치법규ID": ch.ordin_id, "자치법규일련번호": ch.serial, "시행일자": ch.new_date})
        body = sync.fetch_body(oc, ch.ordin_id)
        rows = sync.proposal_rows(ch, sync.articles_from_body(body))
        lines.append(f"## {ch.jurisdiction} · {ch.name}  ({ch.old_date} → {ch.new_date})")
        if not rows:
            lines += ["- 점검 대상 조문을 찾지 못했습니다(조문 제목 확인 필요). 제안하지 않음", ""]
            continue
        new_cls = classify_ordinances.classify(rows[0])
        old_cls = draft.get((ch.jurisdiction, ch.name)) or next(
            (v for (j, n), v in draft.items() if sync._norm(j) == sync._norm(ch.jurisdiction) and sync._norm(n) == sync._norm(ch.name)), None)
        diffs = sync.diff_classified(old_cls, new_cls)
        lines += [f"- {f}: `{o}` → `{n}`" for f, o, n in diffs] or ["- 분류 결과 변화 없음(조문 문구만 바뀜)"]
        if new_cls["review_needed"] == "Y":
            lines.append(f"- 검토필요: {new_cls['review_reason']}")
        lines.append("")
        proposal += rows
    if cs.missing:
        lines += ["## 목록에서 찾지 못한 기존 조례(폐지·명칭 변경·개편 여부 확인)", ""]
        lines += [f"- {j} · {n}" for j, n in cs.missing]
    sync.write_csv(out_dir / "proposal.csv", proposal, RAW_FIELDS)
    sync.write_csv(out_dir / "law_ids.csv", ids, ["지자체", "조례명", "자치법규ID", "자치법규일련번호", "시행일자"])
    (out_dir / "diff.md").write_text("\n".join(lines), encoding="utf-8")
    shown = out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir
    print(f"제안 {len(proposal)}건 → {shown}/proposal.csv, diff.md (원본은 바꾸지 않았습니다)")


def apply(proposal_path: Path, yes: bool) -> None:
    if not yes:
        sys.exit("diff.md를 검토했다면 --yes를 붙여 다시 실행하세요.")
    proposal = sync.read_csv(proposal_path)
    raw = sync.read_csv(RAW)
    updated, n = sync.apply_proposal(raw, proposal, lambda r: classify_ordinances.classify(r)["row_role"] == "점검대상")
    sync.write_csv(RAW, updated, RAW_FIELDS)
    classify_ordinances.main(classify_ordinances.DEFAULT_SRC, classify_ordinances.DEFAULT_DST)
    print(f"{n}건 반영, 분류 초안을 다시 만들었습니다. git diff로 확인한 뒤 커밋하세요.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--query", default=QUERY)
    c.add_argument("--out", type=Path, default=ORD_DIR / "sync" / date.today().strftime("%Y%m%d"))
    a = sub.add_parser("apply")
    a.add_argument("proposal", type=Path)
    a.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if args.cmd == "check":
        check(args.out, args.query)
    else:
        apply(args.proposal, args.yes)


if __name__ == "__main__":
    main()
