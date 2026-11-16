"""단계 6: LLM 공급자 추상화·전처리·분류/추출·사용량 로그·안내문 틀 (외부 호출 없음)."""

import csv
import io

import zipfile
from datetime import date
from types import SimpleNamespace

import pytest

import compare_providers
from core import letters
from core.conditions import BusinessType
from core.llm import extractor, factory, usage_log
from core.llm.base import LLMError, LLMRefusalError, LLMValidationError, Part, Usage, strict_json_schema
from core.llm.claude import ClaudeProvider
from core.llm.gemini import GeminiProvider
from core.llm.mock import MockProvider, sample_extract
from core.llm.preprocess import MAX_FILE_BYTES, UploadedFile, read_hwpx, to_parts
from core.llm.schemas import ClassifyOut, ExtractOut
from core.notices import load_notices, notices_for, save_notice

ADDRESS = "서울특별시 종로구 청운동 2번지"
BODY = "소규모 노후 건축물 안전점검 신청 안내 본문입니다. " * 10


# ---------------------------------------------------------------- 도우미


def hwpx_bytes(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    hp = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    ps = "".join(f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>" for t in paragraphs)
    if table:
        rows = "".join(
            "<hp:tr>" + "".join(f"<hp:tc><hp:subList><hp:p><hp:run><hp:t>{c}</hp:t></hp:run></hp:p></hp:subList></hp:tc>" for c in r) + "</hp:tr>"
            for r in table
        )
        ps += f"<hp:p><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>"
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" {hp}>{ps}</hs:sec>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", xml)
    return buf.getvalue()


class FakeProvider:
    """미리 정한 원문 JSON/텍스트를 차례로 돌려주는 가짜 공급자(실제 공급자처럼 name != mock)."""

    def __init__(self, json_outputs=(), text_outputs=(), name="fake"):
        self.name, self.model = name, "fake-model"
        self.json_outputs, self.text_outputs = list(json_outputs), list(text_outputs)
        self.seen_parts: list[list[Part]] = []
        self.seen_prompts: list[str] = []

    def generate_json(self, system, parts, schema):
        from core.llm.base import parse_with_retry

        self.seen_parts.append(parts)
        usage = Usage(self.name, self.model)

        def call(hint):
            return self.json_outputs.pop(0), 100, 20

        return parse_with_retry(call, schema, usage), usage

    def generate_text(self, system, prompt):
        self.seen_prompts.append(prompt)
        out = self.text_outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out, Usage(self.name, self.model, 50, 30)


@pytest.fixture
def usage_file(tmp_path, monkeypatch):
    path = tmp_path / "llm_usage.csv"
    monkeypatch.setenv("LLM_USAGE_LOG", str(path))
    return path


# ---------------------------------------------------------------- 스키마·팩토리


def test_strict_schema_has_no_open_objects():
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "object":
                assert n.get("additionalProperties") is False
                assert set(n["required"]) == set(n["properties"])
            assert "$ref" not in n and "default" not in n and "title" not in n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(strict_json_schema(ExtractOut))
    walk(strict_json_schema(ClassifyOut))


@pytest.mark.parametrize(
    "env, reason_part",
    [
        ({"LLM_PROVIDER": "mock"}, "LLM_PROVIDER=mock"),
        ({"LLM_PROVIDER": "claude", "LLM_MODEL_EXTRACT": "m"}, "ANTHROPIC_API_KEY"),
        ({"LLM_PROVIDER": "claude", "ANTHROPIC_API_KEY": "k"}, "LLM_MODEL_EXTRACT"),
        ({"LLM_PROVIDER": "gemini", "LLM_MODEL_EXTRACT": "m"}, "GEMINI_API_KEY"),
    ],
)
def test_factory_falls_back_to_mock(monkeypatch, env, reason_part):
    monkeypatch.setattr(factory, "load_dotenv", lambda *a, **k: None)
    for k in ("LLM_PROVIDER", "LLM_MODEL_EXTRACT", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    st = factory.status("extract")
    assert st.is_mock and reason_part in st.reason
    assert isinstance(factory.get_provider("extract"), MockProvider)


def test_factory_builds_real_provider_without_calling(monkeypatch):
    monkeypatch.setattr(factory, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # 실제 .env 값이 섞이지 않게
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("LLM_MODEL_EXTRACT", "claude-opus-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    p = factory.get_provider("extract")
    assert isinstance(p, ClaudeProvider) and p.model == "claude-opus-5-5"
    assert factory.available_providers() == ["claude"]


# ---------------------------------------------------------------- 재시도·검증


def test_validation_retry_once_then_success():
    good = ClassifyOut(business_type="APPLY_INSPECTION", evidence="x", reason="r", has_repair_section=False).model_dump_json()
    p = FakeProvider(json_outputs=['{"business_type": "모름"}', good])
    out, usage = p.generate_json("s", [Part.of_text("t")], ClassifyOut)
    assert out.business_type == "APPLY_INSPECTION" and usage.retries == 1
    assert (usage.input_tokens, usage.output_tokens) == (200, 40)


def test_validation_fails_twice_raises_with_raw():
    p = FakeProvider(json_outputs=["{}", '{"bad": 1}'])
    with pytest.raises(LLMValidationError) as e:
        p.generate_json("s", [Part.of_text("t")], ClassifyOut)
    assert e.value.raw == '{"bad": 1}'


# ---------------------------------------------------------------- Claude·Gemini 요청 모양(가짜 클라이언트)


class FakeAnthropic:
    def __init__(self, responses):
        self.calls = []
        outer = self

        class Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                return responses.pop(0)

        self.messages = Msgs()
        self.beta = SimpleNamespace(messages=Msgs())


def claude_resp(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


def test_claude_request_shape_and_fallbacks(monkeypatch):
    monkeypatch.delenv("LLM_CLAUDE_FALLBACKS", raising=False)
    good = ClassifyOut(business_type="REPAIR_SUPPORT", evidence="보수비 지원", reason="r", has_repair_section=True).model_dump_json()
    client = FakeAnthropic([claude_resp(good)])
    p = ClaudeProvider("claude-opus-5-5", client=client)
    parts = [Part.of_text("[파일: a.pdf]"), Part.of_bytes(b"%PDF-1.4", "application/pdf"), Part.of_bytes(b"\x89PNG", "image/png")]
    out, usage = p.generate_json("sys", parts, ClassifyOut)
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    types_ = [b["type"] for b in kw["messages"][0]["content"]]
    assert types_ == ["document", "image", "text"]  # 문서·이미지를 텍스트보다 앞에
    assert "thinking" not in kw  # 최신 모델은 thinking을 끌 수 없으므로 보내지 않는다
    assert out.business_type == "REPAIR_SUPPORT" and usage.input_tokens == 1000


def test_claude_fallbacks_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("LLM_CLAUDE_FALLBACKS", "off")
    client = FakeAnthropic([claude_resp("안내문")])
    p = ClaudeProvider("m", client=client)
    text, _ = p.generate_text("s", "p")
    assert text == "안내문" and "fallbacks" not in client.calls[0]


def test_claude_refusal():
    p = ClaudeProvider("m", client=FakeAnthropic([claude_resp("", stop="refusal")]))
    with pytest.raises(LLMRefusalError):
        p.generate_text("s", "p")


def test_claude_needs_model():
    with pytest.raises(LLMError):
        ClaudeProvider("", client=FakeAnthropic([]))


def test_gemini_request_shape():
    seen = {}

    def generate_content(model, contents, config):
        seen.update(model=model, contents=contents, config=config)
        good = ClassifyOut(business_type="APPLY_INSPECTION", evidence=None, reason="r", has_repair_section=False).model_dump_json()
        return SimpleNamespace(text=good, candidates=[SimpleNamespace(finish_reason="STOP")],
                               usage_metadata=SimpleNamespace(prompt_token_count=900, candidates_token_count=100))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    p = GeminiProvider("gemini-test", client=client)
    out, usage = p.generate_json("sys", [Part.of_bytes(b"%PDF", "application/pdf"), Part.of_text("t")], ClassifyOut)
    assert seen["model"] == "gemini-test"
    assert seen["config"].response_mime_type == "application/json" and seen["config"].response_json_schema
    assert len(seen["contents"][0].parts) == 2
    assert out.business_type == "APPLY_INSPECTION" and (usage.input_tokens, usage.output_tokens) == (900, 100)


# ---------------------------------------------------------------- 전처리


def test_hwpx_tables_become_markdown():
    text = read_hwpx(hwpx_bytes(["소규모 노후건축물 안전점검 지원 공고"], [["구분", "기준"], ["층수", "3층 이하"], ["연면적", "200㎡ 미만"]]))
    assert "소규모 노후건축물 안전점검 지원 공고" in text
    assert "| 구분 | 기준 |" in text and "| 층수 | 3층 이하 |" in text and "| 연면적 | 200㎡ 미만 |" in text
    assert text.count("3층 이하") == 1  # 표 내용이 문단으로 한 번 더 나오지 않음


def test_to_parts_bundle_and_warnings():
    files = [
        UploadedFile("공고.hwpx", hwpx_bytes([BODY])),
        UploadedFile("앞면.png", b"\x89PNG..."),
        UploadedFile("뒷면.JPG", b"\xff\xd8..."),
        UploadedFile("본문.pdf", b"%PDF-1.4"),
        UploadedFile("짧은.hwpx", hwpx_bytes(["짧음"])),
        UploadedFile("큰.pdf", b"0" * (MAX_FILE_BYTES + 1)),
        UploadedFile("메모.txt", b"x"),
        UploadedFile("깨진.hwp", b"not an ole file"),
    ]
    pre = to_parts(files)
    sent = [p for p in pre.parts if p.data is not None]
    assert [p.mime for p in sent] == ["image/png", "image/jpeg", "application/pdf"]
    assert len({p.name for p in pre.parts}) == 4  # 한 요청에 4개 파일 모두
    assert len(pre.skipped) == 4
    assert any("8MB" in s for s in pre.skipped) and any("글자가" in s for s in pre.skipped)
    assert any("4개를 넣지 못했습니다" in w for w in pre.warnings)


# ---------------------------------------------------------------- 분류·추출 변환


def test_to_notice_conversion_rules():
    out = sample_extract().model_copy(deep=True)
    out.floors_text.value = "2층 미만"
    out.area_text.value = "연면적 5백제곱미터 미만"
    out.local_gov.value = "없는시 없는구"
    out.apply_start.value, out.apply_end.value = "2026-03-02", "2026-02-30"
    out.selection_method.value = "추첨"
    out.source_type = "NEWS"
    r = extractor.to_notice(out, "t")
    n = r.notice
    assert (n.max_floors, n.floors_bound, n.max_area, n.area_bound) == (2, "LT", 500.0, "LT")
    assert n.sigungu_codes == [] and any("시군구코드" in i for i in r.issues)
    assert n.apply_start == date(2026, 3, 2) and n.apply_end is None and any("없는 날짜" in i for i in r.issues)
    assert n.selection_method == "기타"
    assert any("원문 공고를 확인" in i for i in r.issues)
    assert n.reviewed is False and n.business_type == BusinessType.APPLY_INSPECTION
    assert n.evidence["max_floors"] == "3층 이하"  # 원문 근거는 그대로


def test_to_notice_built_before_year():
    out = sample_extract().model_copy(deep=True)
    out.min_years.value = None
    out.built_before_year.value = 1994
    out.built_before_inclusive.value = None
    n = extractor.to_notice(out, "t").notice
    assert (n.years_basis, n.built_before_year, n.built_before_inclusive) == ("BUILT_BEFORE_YEAR", 1994, None)


def test_floor_text_without_bound_is_not_guessed():
    out = sample_extract().model_copy(deep=True)
    out.floors_text.value = "3층"
    r = extractor.to_notice(out, "t")
    assert r.notice.max_floors is None and any("이하/미만" in i for i in r.issues)


def test_classify_non_apply_stops(usage_file):
    p = FakeProvider(json_outputs=[ClassifyOut(business_type="REPAIR_SUPPORT", evidence="보수비 지원", reason="r", has_repair_section=False).model_dump_json()])
    c = extractor.classify([Part.of_text(BODY)], p)
    assert not c.is_apply_inspection and c.evidence == "보수비 지원"


# ---------------------------------------------------------------- 사용량 로그: 본문·주소 없음


def test_usage_log_has_no_body_or_address(usage_file):
    parts = [Part.of_text(f"[파일: 공고.hwpx]\n{BODY}\n접수처 {ADDRESS}")]
    p = FakeProvider(json_outputs=[
        ClassifyOut(business_type="APPLY_INSPECTION", evidence=ADDRESS, reason=ADDRESS, has_repair_section=False).model_dump_json(),
        sample_extract().model_dump_json(),
    ], text_outputs=[letters.BUILTIN["official"]])
    extractor.classify(parts, p)
    extractor.extract(parts, p)
    n = extractor.to_notice(sample_extract(), "t").notice
    letters.make_template_llm(n, "official", p)
    raw = usage_file.read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    assert [r["task"] for r in rows] == ["classify", "extract", "template"]
    assert list(rows[0]) == usage_log.FIELDS
    for bad in (ADDRESS, "청운동", "안전점검", "공고.hwpx", "건축물", "접수"):
        assert bad not in raw
    assert all(len(r["doc_hash"]) == 16 for r in rows)


def test_usage_log_rejects_non_hash(usage_file):
    with pytest.raises(ValueError):
        usage_log.record(Usage("x", "m"), "extract", ADDRESS)


def test_mock_provider_is_not_logged(usage_file):
    extractor.extract([Part.of_text(BODY)], MockProvider())
    assert not usage_file.exists()


# ---------------------------------------------------------------- 안내문 틀 (LLM)


def test_template_llm_valid_used_and_input_has_no_building_data():
    n = extractor.to_notice(sample_extract(), "t").notice
    p = FakeProvider(text_outputs=[letters.BUILTIN["elder"]])
    text, warns, from_llm = letters.make_template_llm(n, "elder", p)
    assert from_llm and warns == [] and text == letters.BUILTIN["elder"].strip()
    prompt = p.seen_prompts[0]
    assert "2026. 7. 1." in prompt and "중구청 건축과" in prompt  # 공고 조건만
    for bad in ("청운동", "사용승인", "연면적 1"):
        assert bad not in prompt


@pytest.mark.parametrize(
    "llm_text",
    ["{지번주소} 건물은 연면적 200㎡ 이하라 선정되었습니다. {판정안내}\n" + letters.REVIEW_LINE, LLMError("타임아웃")],
)
def test_template_llm_invalid_falls_back(llm_text):
    p = FakeProvider(text_outputs=[llm_text])
    text, warns, from_llm = letters.make_template_llm(None, "official", p)
    assert text == letters.BUILTIN["official"] and not from_llm and warns


# ---------------------------------------------------------------- 탭1 흐름(mock) → 저장 → 탭2 목록


def test_mock_upload_extract_review_save_flow(tmp_path):
    pre = to_parts([UploadedFile("공고.hwpx", hwpx_bytes([BODY]))])
    p = MockProvider()
    c = extractor.classify(pre.parts, p)
    assert c.is_apply_inspection
    r = extractor.extract(pre.parts, p)
    reviewed = r.notice.model_copy(update={"reviewed": True})
    save_notice(reviewed, directory=tmp_path)
    with pytest.raises(FileExistsError):
        save_notice(reviewed, directory=tmp_path)
    loaded = load_notices(tmp_path)
    assert loaded[0].reviewed and notices_for("30140", loaded)[0].notice_id == reviewed.notice_id


# ---------------------------------------------------------------- 공급자 비교 스크립트(mock)


def test_compare_providers_with_mock(tmp_path):
    case = tmp_path / "daejeon"
    case.mkdir()
    (case / "공고.hwpx").write_bytes(hwpx_bytes([BODY]))
    truth = extractor.to_notice(sample_extract(), "daejeon").notice
    (case / "truth.json").write_text(truth.model_dump_json(), encoding="utf-8")
    s = compare_providers.run(MockProvider(), [case])
    assert s.cases == 1 and s.classify_ok == 1 and s.matched == s.compared == len(compare_providers.COMPARE_FIELDS)
    assert dict(s.by_format) == {"hwpx": [s.compared, s.compared]}


# ---------------------------------------------------------------- 실제 공급자 (기본 skip)


@pytest.mark.live
def test_live_provider_extract(usage_file):
    st = factory.status("extract")
    if st.is_mock:
        pytest.skip(st.reason)
    pre = to_parts([UploadedFile("공고.hwpx", hwpx_bytes([BODY], [["구분", "기준"], ["층수", "3층 이하"], ["연면적", "200㎡ 미만"]]))])
    r = extractor.extract(pre.parts, factory.get_provider("extract"))
    assert r.notice.max_floors == 3 and r.notice.area_bound == "LT"
    rows = list(csv.DictReader(io.StringIO(usage_file.read_text(encoding="utf-8"))))
    assert rows[-1]["task"] == "extract" and int(rows[-1]["input_tokens"]) > 0


def test_gemini_retries_503_and_timeout(monkeypatch):
    from google.genai import errors as genai_errors
    from tenacity import wait_none

    import core.llm.gemini as gem

    monkeypatch.setattr(gem, "RETRY_WAIT", wait_none())

    class ReadTimeout(Exception):  # httpx 계열 시간 초과와 같은 이름 규칙
        pass

    good = ClassifyOut(business_type="APPLY_INSPECTION", evidence=None, reason="r", has_repair_section=False).model_dump_json()
    seq = [genai_errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}), ReadTimeout("slow")]

    def generate_content(model, contents, config):
        if seq:
            raise seq.pop(0)
        return SimpleNamespace(text=good, candidates=[SimpleNamespace(finish_reason="STOP")],
                               usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1))

    p = GeminiProvider("m", client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    out, _ = p.generate_json("s", [Part.of_text("t")], ClassifyOut)
    assert out.business_type == "APPLY_INSPECTION" and seq == []


def test_gemini_404_hint():
    from google.genai import errors as genai_errors

    def generate_content(model, contents, config):
        raise genai_errors.ClientError(404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}})

    p = GeminiProvider("없는모델", client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    with pytest.raises(LLMError) as e:
        p.generate_text("s", "p")
    assert "모델명" in str(e.value)
