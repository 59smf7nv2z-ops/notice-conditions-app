"""업로드한 공고 파일 → LLM 요청 조각(Part). 토큰을 아끼려고 글자로 읽을 수 있는 문서는 텍스트·마크다운으로 바꾼다.

- HWPX: 본문 + 표(마크다운). HWP(바이너리, olefile): 문단 텍스트만(표 구조는 사라지고 셀 내용은 줄로 남음).
- PDF(pymupdf): 쪽마다 글자층을 읽어 본문 + 표(마크다운). 글자층이 없거나 깨진 쪽(스캔본)만 이미지로 바꾼다.
- DOCX(python-docx): 문단·제목·표를 문서 순서대로. XLSX(openpyxl): 시트별 마크다운 표(계산된 값).
- PNG·JPG와 스캔 쪽(pillow): 흑백(회색조)·대비 보정 후 긴 변 IMAGE_MAX_EDGE 이하로 줄인다.
  세로로 긴 리플릿은 글자가 뭉개지지 않게 폭을 유지한 채 위아래로 잘라(겹침 포함) 여러 장으로 보낸다.
  이미지 토큰은 대략 가로×세로/750이라 크기가 비용을 정한다. 회색조는 전송 용량을 줄이고 색 배경 대비를 높인다.
- 업로드 파일 수와 만들어진 파일 수를 비교해 다르면 경고한다(예전 '리플릿 이미지 한 장 누락' 오류 재발 방지).
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

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
TEXT_EXTS = {".hwpx", ".hwp", ".docx", ".xlsx", ".txt"}
PDF_EXTS = {".pdf"}
ACCEPTED = tuple(sorted(TEXT_EXTS | IMAGE_EXTS | PDF_EXTS))

# 이미지: 긴 변 1568px·약 1.15MP가 이전 세대 모델의 처리 한도라 이보다 크게 보내도 서버에서 줄인다.
# 한 장(조각)당 약 1,500 토큰. 더 큰 해상도를 받는 모델에서 작은 글씨가 안 읽히면 .env LLM_IMAGE_MAX_EDGE로 올린다.
IMAGE_MAX_EDGE = 1568
IMAGE_MAX_PIXELS = 1_150_000
TILE_OVERLAP = 48  # 잘린 경계의 글자 줄이 양쪽 조각에 다 들어가게
MAX_TILES_PER_IMAGE = 8
PDF_RENDER_DPI = 150  # 스캔 쪽을 이미지로 바꿀 때(A4 폭 약 1240px)
PDF_MAX_PAGES = 30
PAGE_MIN_TEXT = 40  # 쪽 글자층이 이보다 적으면 스캔 쪽으로 본다
XLSX_MAX_ROWS = 300


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
    return md_table(rows)


def _cell(v) -> str:
    return " ".join(str(v).split()).replace("|", "／") if v is not None else ""


def md_table(rows: list[list]) -> list[str]:
    """2차원 값 → 마크다운 표 줄. 빈 행과 끝의 빈 열은 버린다(토큰 절약)."""
    rows = [[_cell(c) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max((max((i + 1 for i, c in enumerate(r) if c), default=0) for r in rows), default=0)
    rows = [(r + [""] * width)[:width] for r in rows]
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


# ---------------------------------------------------------------- DOCX · XLSX · TXT


def read_docx(data: bytes) -> str:
    """문단·제목·표를 문서 순서대로. 병합 셀은 python-docx가 같은 셀을 반복해 주므로 이웃 중복을 지운다."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    for el in d.element.body.iterchildren():
        name = _local(el.tag)
        if name == "p":
            p = Paragraph(el, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"(?:Heading|제목)\s*(\d)", style)
            lines.append(("#" * min(int(m.group(1)), 4) + " " if m else "") + text)
        elif name == "tbl":
            rows = []
            for r in Table(el, d).rows:
                cells: list[str] = []
                for c in r.cells:
                    t = c.text
                    if not cells or cells[-1] != t:
                        cells.append(t)
                rows.append(cells)
            lines += md_table(rows) + [""]
    return "\n".join(lines).strip()


def read_xlsx(data: bytes) -> str:
    """시트별 마크다운 표. 수식은 저장된 계산값을 쓴다(data_only)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: list[str] = []
    try:
        for ws in wb.worksheets:
            rows = []
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                if i >= XLSX_MAX_ROWS:
                    out.append(f"(시트 '{ws.title}' {XLSX_MAX_ROWS}행 이후 생략)")
                    break
                rows.append(list(r))
            table = md_table(rows)
            if table:
                out += [f"## 시트: {ws.title}"] + table + [""]
    finally:
        wb.close()
    return "\n".join(out).strip()


def read_txt(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------- 이미지 (pillow)


def _image_limits() -> tuple[int, int]:
    import os

    try:
        edge = int(os.environ.get("LLM_IMAGE_MAX_EDGE") or IMAGE_MAX_EDGE)
    except ValueError:
        edge = IMAGE_MAX_EDGE
    edge = max(800, min(edge, 2576))
    return edge, max(IMAGE_MAX_PIXELS, int(IMAGE_MAX_PIXELS * (edge / IMAGE_MAX_EDGE) ** 2))


def prepare_image(data: bytes) -> list[bytes]:
    """사진·스캔 → 회색조 PNG 조각들.

    1) 휴대폰 사진의 회전 정보(EXIF)를 반영  2) 회색조 + 자동 대비(위아래 1% 잘라 배경 얼룩 정리).
       글자가 끊길 수 있어 완전 흑백(이진화)은 하지 않는다.
    3) 폭을 긴 변 한도 이하로 줄이고(확대는 안 함), 한 조각 픽셀 한도를 넘으면 위아래로 겹쳐 자른다.
    """
    from PIL import Image, ImageOps

    edge, max_px = _image_limits()
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = ImageOps.autocontrast(im.convert("L"), cutoff=1)
    w, h = im.size
    if w > edge:  # 폭을 한도까지 줄인다(세로 길이는 아래에서 조각으로 나눔)
        im = im.resize((edge, max(1, round(h * edge / w))), Image.Resampling.LANCZOS)
    w, h = im.size
    if w * h > max_px and h <= w:  # 가로형은 자르지 않고 비율 유지 축소
        s = (max_px / (w * h)) ** 0.5
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.Resampling.LANCZOS)
        w, h = im.size
    tile_h = max(200, min(edge, max_px // max(w, 1)))
    if h > tile_h:
        n = -(-(h - TILE_OVERLAP) // (tile_h - TILE_OVERLAP))
        if n > MAX_TILES_PER_IMAGE:  # 너무 길면 조각 수를 지키려고 전체를 줄인다
            s = (MAX_TILES_PER_IMAGE * (tile_h - TILE_OVERLAP) + TILE_OVERLAP) / h
            im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.Resampling.LANCZOS)
            w, h = im.size
            tile_h = max(200, min(edge, max_px // max(w, 1)))
    out: list[bytes] = []
    top = 0
    while True:
        bottom = min(h, top + tile_h)
        buf = io.BytesIO()
        im.crop((0, top, w, bottom)).save(buf, "PNG", optimize=True)
        out.append(buf.getvalue())
        if bottom >= h:
            break
        top = bottom - TILE_OVERLAP
    return out


# ---------------------------------------------------------------- PDF (pymupdf)


def _garbled(text: str) -> bool:
    """글꼴에 유니코드 정보가 없어 깨진 글자층(�, 사용자 정의 영역 문자)이 많은지."""
    if not text:
        return False
    bad = sum(1 for ch in text if ch == "�" or 0xE000 <= ord(ch) <= 0xF8FF)
    return bad / len(text) > 0.05


@dataclass
class PdfRead:
    text: str  # 글자층을 읽은 쪽의 본문·표(마크다운). 쪽 표시 포함
    scanned_pages: list[int]  # 이미지로 보내야 하는 쪽(1부터)
    images: list[tuple[int, list[bytes]]]  # (쪽, 이미지 조각)
    page_count: int


def read_pdf(data: bytes) -> PdfRead:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass:
            raise ValueError("암호가 걸린 PDF입니다")
        pages_out: list[str] = []
        scanned: list[int] = []
        images: list[tuple[int, list[bytes]]] = []
        n = min(doc.page_count, PDF_MAX_PAGES)
        for i in range(n):
            page = doc[i]
            try:
                tables = page.find_tables().tables
            except Exception:  # noqa: BLE001 - 표 찾기 실패는 본문만으로
                tables = []
            rects = [pymupdf.Rect(t.bbox) for t in tables]
            items: list[tuple[float, float, list[str]]] = []
            for b in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, text, _, btype = b[:7]
                if btype != 0 or not text.strip():
                    continue
                r = pymupdf.Rect(x0, y0, x1, y1)
                if any(r.intersect(t).get_area() > 0.5 * r.get_area() for t in rects if r.get_area() > 0):
                    continue
                items.append((y0, x0, [" ".join(text.split())]))
            for t, r in zip(tables, rects):
                try:
                    # Table.extract()는 띄어쓰기를 잃는 경우가 있어("3 or less" → "3orless") 칸 영역 글자를 직접 읽는다
                    rows = [[page.get_textbox(c) if c else "" for c in row.cells] for row in t.rows]
                except Exception:  # noqa: BLE001
                    continue
                items.append((r.y0, r.x0, md_table(rows) + [""]))
            items.sort(key=lambda it: (round(it[0]), it[1]))
            body = "\n".join(line for _, _, ls in items for line in ls).strip()
            if len(body) < PAGE_MIN_TEXT or _garbled(body):
                scanned.append(i + 1)
                pix = page.get_pixmap(dpi=PDF_RENDER_DPI, colorspace=pymupdf.csGRAY)
                images.append((i + 1, prepare_image(pix.tobytes("png"))))
                continue
            pages_out.append(f"--- {i + 1}쪽 ---\n{body}")
        if doc.page_count > PDF_MAX_PAGES:
            pages_out.append(f"(전체 {doc.page_count}쪽 중 {PDF_MAX_PAGES}쪽까지만 읽음)")
        return PdfRead("\n\n".join(pages_out), scanned, images, doc.page_count)
    finally:
        doc.close()


# ---------------------------------------------------------------- 묶음 처리


TEXT_READERS = {".hwpx": read_hwpx, ".hwp": read_hwp, ".docx": read_docx, ".xlsx": read_xlsx, ".txt": read_txt}


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
        if ext in IMAGE_EXTS:
            try:
                tiles = prepare_image(f.data)
            except Exception as e:  # noqa: BLE001
                res.skipped.append(f"{name}: 이미지를 열지 못했습니다({e})")
                continue
            label = f"[파일: {name}]" + (f" (세로로 {len(tiles)}조각, 경계 겹침)" if len(tiles) > 1 else "")
            res.parts.append(Part.of_text(label, name=name))
            res.parts += [Part.of_bytes(t, "image/png", name=name) for t in tiles]
            continue
        if ext in PDF_EXTS:
            try:
                pdf = read_pdf(f.data)
            except Exception as e:  # noqa: BLE001
                res.skipped.append(f"{name}: 읽기 실패({e})")
                continue
            if pdf.text:
                res.parts.append(Part.of_text(f"[파일: {name}]\n{pdf.text}", name=name))
                previews.append(pdf.text[:2000])
            for page_no, tiles in pdf.images:
                res.parts.append(Part.of_text(f"[파일: {name} {page_no}쪽 이미지(글자층 없음)]", name=name))
                res.parts += [Part.of_bytes(t, "image/png", name=name) for t in tiles]
            if pdf.scanned_pages and pdf.text:
                res.warnings.append(f"{name}: {', '.join(map(str, pdf.scanned_pages))}쪽은 글자층이 없어 이미지로 보냅니다")
            if pdf.page_count > PDF_MAX_PAGES:
                res.warnings.append(f"{name}: {pdf.page_count}쪽 중 앞 {PDF_MAX_PAGES}쪽만 보냅니다")
            continue
        if ext in TEXT_READERS:
            try:
                text = TEXT_READERS[ext](f.data)
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
