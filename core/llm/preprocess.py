"""업로드한 공고 파일 → LLM 요청 조각(Part).

- HWP·HWPX는 Claude·Gemini 모두 직접 읽지 못한다 → 텍스트로 바꾼다.
  기존 grok 웹앱(frontend_grok/lib/readers.ts)의 변환 방식을 옮기고, HWPX 표는 마크다운 표로 바꿨다.
  HWP(바이너리)는 문단 텍스트만 뽑으므로 표 구조가 사라진다(셀 내용은 줄로 남음) → 표가 중요한 공고는 PDF 권장.
- PDF·PNG·JPG는 원본 그대로 넘긴다. 리플릿처럼 여러 장이면 한 요청에 모두 넣는다.
  업로드 파일 수와 만들어진 조각 수를 비교해 다르면 경고한다(예전 '리플릿 이미지 한 장 누락' 오류 재발 방지).
- 파일당 8MB. 업로드 파일은 메모리에서만 처리하고 디스크에 쓰지 않는다.
"""

from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field

import olefile

from core.llm.base import Part

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED = 16 * 1024 * 1024  # 압축 폭탄 방지
MIN_TEXT = 150  # 이보다 적게 읽히면 도형·그림 위주 문서로 보고 PDF·이미지 변환을 권한다

MIME_BY_EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
TEXT_EXTS = {".hwpx", ".hwp"}
ACCEPTED = tuple(sorted(TEXT_EXTS | set(MIME_BY_EXT)))


@dataclass
class UploadedFile:
    name: str
    data: bytes


@dataclass
class Preprocessed:
    parts: list[Part] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # "파일명: 사유"
    warnings: list[str] = field(default_factory=list)
    text_preview: str = ""  # 화면 확인용(저장하지 않음)


def _ext(name: str) -> str:
    i = name.rfind(".")
    return name[i:].lower() if i >= 0 else ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- HWPX


def _texts(elem: ET.Element, skip_tables: bool = True) -> str:
    out = []
    for child in elem:
        name = _local(child.tag)
        if skip_tables and name == "tbl":
            continue
        if name == "t" and child.text:
            out.append(child.text)
        out.append(_texts(child, skip_tables))
    return "".join(out)


def _table_markdown(tbl: ET.Element) -> list[str]:
    rows = []
    for tr in tbl.iter():
        if _local(tr.tag) != "tr":
            continue
        cells = []
        for tc in tr:
            if _local(tc.tag) != "tc":
                continue
            text = " ".join(t.text.strip() for t in tc.iter() if _local(t.tag) == "t" and t.text and t.text.strip())
            cells.append(text.replace("|", "／"))
        if cells:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def _walk_section(elem: ET.Element, lines: list[str]) -> None:
    for child in elem:
        name = _local(child.tag)
        if name == "p":
            text = _texts(child).strip()
            if text:
                lines.append(text)
            for tbl in (e for e in child.iter() if _local(e.tag) == "tbl"):
                # 표 안의 표는 바깥 표에서 함께 펼쳐지므로, p에서 바로 닿는 표만
                lines.extend(_table_markdown(tbl))
                lines.append("")
                break
        elif name == "tbl":
            lines.extend(_table_markdown(child))
        else:
            _walk_section(child, lines)


def read_hwpx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
            raise ValueError("압축을 풀면 용량이 너무 큽니다")
        names = sorted(
            (n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n.split("/")[-1]).group()),
        )
        lines: list[str] = []
        for n in names:
            root = ET.fromstring(z.read(n))
            _walk_section(root, lines)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- HWP 5.0 (바이너리)

_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
_LONG_CTRL = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
HWPTAG_PARA_TEXT = 67


def _hwp_clean(raw: bytes) -> str:
    out = []
    i, n = 0, len(raw) // 2
    while i < n:
        code = struct.unpack_from("<H", raw, i * 2)[0]
        if code in _LONG_CTRL:
            if code == 9:
                out.append(" ")
            i += 8
        elif code in _CHAR_CTRL:
            if code in (10, 13):
                out.append("\n")
            i += 1
        else:
            out.append(chr(code))
            i += 1
    return "".join(out)


def read_hwp(data: bytes) -> str:
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise ValueError("HWP 문서가 아닙니다")
        flags = header[36] if len(header) > 36 else 0
        if flags & 2:
            raise ValueError("암호가 걸린 문서입니다")
        compressed = bool(flags & 1)
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and re.fullmatch(r"Section\d+", e[1])),
            key=lambda e: int(e[1][7:]),
        )
        paras: list[str] = []
        for sec in sections[:64]:
            body = ole.openstream(sec).read()
            if compressed:
                d = zlib.decompressobj(-15)
                body = d.decompress(body, MAX_UNCOMPRESSED)
                if d.unconsumed_tail:
                    raise ValueError("풀어 낸 본문이 너무 큽니다")
            i = 0
            while i + 4 <= len(body):
                h = struct.unpack_from("<I", body, i)[0]
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                i += 4
                if size == 0xFFF:
                    if i + 4 > len(body):
                        break
                    size = struct.unpack_from("<I", body, i)[0]
                    i += 4
                if tag == HWPTAG_PARA_TEXT and i + size <= len(body):
                    paras.append(_hwp_clean(body[i : i + size]))
                i += size
    finally:
        ole.close()
    return "\n".join(p for p in paras if p.strip())


# ---------------------------------------------------------------- 묶음 처리


def to_parts(files: list[UploadedFile]) -> Preprocessed:
    """여러 파일 = 한 공고 묶음 → Part 목록."""
    res = Preprocessed()
    previews = []
    for f in files:
        name = f.name.replace("/", "_").replace("\\", "_")
        ext = _ext(name)
        if len(f.data) > MAX_FILE_BYTES:
            res.skipped.append(f"{name}: 파일이 8MB를 넘습니다")
            continue
        if ext in MIME_BY_EXT:
            res.parts.append(Part.of_text(f"[파일: {name}]", name=name))
            res.parts.append(Part.of_bytes(f.data, MIME_BY_EXT[ext], name=name))
            continue
        if ext in TEXT_EXTS:
            try:
                text = read_hwpx(f.data) if ext == ".hwpx" else read_hwp(f.data)
            except Exception as e:  # noqa: BLE001 - 파일 하나 실패는 건너뛰고 알린다
                res.skipped.append(f"{name}: 읽기 실패({e}). PDF나 이미지로 저장해 올려 주세요")
                continue
            if len(text.strip()) < MIN_TEXT:
                res.skipped.append(f"{name}: 읽어 낸 글자가 {len(text.strip())}자뿐입니다(도형·그림 위주 문서일 수 있음). PDF나 이미지로 저장해 올려 주세요")
                continue
            res.parts.append(Part.of_text(f"[파일: {name}]\n{text}", name=name))
            previews.append(text[:2000])
            if ext == ".hwp" and "|" not in text:
                res.warnings.append(f"{name}: HWP는 표 구조 없이 글자만 읽습니다. 조건이 표에 있으면 결과를 원문과 꼭 대조하세요")
            continue
        res.skipped.append(f"{name}: 지원하지 않는 형식({ext or '확장자 없음'}). 허용: {', '.join(ACCEPTED)}")

    sent_files = {p.name for p in res.parts}
    expected = len(files) - len(res.skipped)
    if len(sent_files) != expected:
        res.warnings.append(f"올린 파일 {len(files)}개 중 요청에 들어간 파일은 {len(sent_files)}개입니다. 빠진 파일이 있는지 확인하세요")
    elif res.skipped:
        res.warnings.append(f"올린 파일 {len(files)}개 중 {len(res.skipped)}개를 넣지 못했습니다")
    res.text_preview = "\n\n".join(previews)
    return res
