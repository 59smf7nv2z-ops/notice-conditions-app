import type { BuildingRecord, Extracted, GuideTone, Verdict } from "./types";
import { flat } from "./download";

/** Tab 3 privacy subcard — keep this sentence verbatim. */
export const PRIVACY_NOTICE =
  "본 안내는 건축물대장 등 공개된 행정정보를 바탕으로 작성되었으며, 성명·연락처 등 개인식별정보는 저장하지 않습니다.";

/** Shown on extract: uploads go to Anthropic when a key is configured. */
export const ANTHROPIC_PROCESS_NOTICE =
  "실제 추출을 누르면 올린 공고 파일이 Anthropic(Claude)으로 전송되어 처리됩니다. 이 환경에 키가 없으면 샘플 결과만 쓰고 전송하지 않습니다.";

export function candidatesOf(buildings: BuildingRecord[]): BuildingRecord[] {
  return buildings.filter((b) => b.overall === "해당" || b.overall === "확인필요");
}

export function buildGuide(notice: Extracted | undefined, buildings: BuildingRecord[]): string {
  const r = notice?.결과 ?? {};
  const gov = flat(r["지자체"]?.value) || "○○구청";
  const program = flat(r["사업명"]?.value) || "소규모 노후 건축물 안전점검";
  const year = flat(r["연도"]?.value);
  const season = flat(r["시기"]?.value);
  const period = flat(r["접수기간"]?.value) || "(접수기간 공고 확인)";
  const method = flat(r["신청자격방법"]?.value);
  const support = flat(r["지원내용"]?.value);
  const list = candidatesOf(buildings);
  const date = new Date().toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" });

  const rows = list.length
    ? list
        .map(
          (b, i) =>
            `  ${i + 1}. ${b.address}${b.ownerHint ? ` (${b.ownerHint})` : ""} — 1차 판정: ${b.overall}`,
        )
        .join("\n")
    : "  (1차 해당·확인필요 건이 없습니다. 건물 정보 대조 탭에서 대상을 판정하세요.)";

  return `${gov}
건축안전센터

「${program}」${year || season ? ` (${[year, season].filter(Boolean).join(" ")})` : ""} 안내

수신: 아래 건축물 소유자(관리자) 귀하
발신: ${gov} 건축안전센터
작성일: ${date}

1. 취지
   소규모 노후 건축물의 안전사고를 예방하기 위하여 공고 조건을 기준으로
   건축물대장 수치를 1차 대조한 결과, 귀하 소유의 건축물이 안전점검
   지원 검토 대상에 포함되어 안내드립니다. 이 안내는 최종 선정 통지가 아니며,
   현장 확인 또는 위원회 심사 결과에 따라 달라질 수 있습니다.

2. 사업 개요
   - 사업명: ${program}
   - 접수기간: ${period}
   - 지원내용: ${support || "(공고 원문 확인)"}
   - 신청 자격·방법: ${method || "(공고 원문 확인)"}

3. 1차 검토 대상 건축물
${rows}

4. 협조 요청
   안내문을 받으신 소유자께서는 접수기간 내에 구비서류를 갖추어 신청하시거나,
   직권 점검 대상인 경우 현장 확인에 협조하여 주시기 바랍니다.
   건축물대장 기재와 실제 현황이 다르면 건축안전센터로 알려 주십시오.

5. 문의
   ${gov} 건축안전센터 (본 문서는 시스템에서 생성한 초안입니다. 발송 전 담당자가 검수하세요.)

끝.`;
}

export function benefitLine(overall: Verdict | undefined, support: string): string {
  if (overall === "해당") return support ? `지자체 지원 ${support} 대상 건물` : "지자체 지원 무료 안전점검 대상 건물";
  if (overall === "확인필요") return "현장·서류 확인 후 지원 여부를 판단할 건물";
  if (overall === "비해당") return "이번 공고 지원 대상에 해당하지 않을 수 있는 건물";
  return "1차 대조 후 안내 문구를 만들 건물";
}

function badgeText(v: Verdict | undefined): string {
  if (v === "해당") return "해당(적합)";
  if (v === "비해당") return "비해당(불적합)";
  if (v === "확인필요") return "확인필요(수동검토)";
  return "미판정";
}

export function buildGuideByTone(
  tone: GuideTone,
  notice: Extracted | undefined,
  building: BuildingRecord | undefined,
  variant = 0,
): string {
  const r = notice?.결과 ?? {};
  const gov = flat(r["지자체"]?.value) || "○○구청";
  const program = flat(r["사업명"]?.value) || "소규모 노후 건축물 안전점검";
  const period = flat(r["접수기간"]?.value) || "(접수기간 공고 확인)";
  const support = flat(r["지원내용"]?.value) || "무료 안전점검";
  const address = building?.address || "(주소 미입력)";
  const use = building?.use || "(용도 미입력)";
  const age = building?.ageYears ? `${building.ageYears}년` : "미확인";
  const approved = building?.approvalDate || "미입력";
  const overall = badgeText(building?.overall);
  const benefit = benefitLine(building?.overall, support);
  const alt = variant % 2 === 1;

  if (tone === "sms") {
    return alt
      ? `[${gov} 건축안전센터] ${program} 안내. ${address} · ${use} · 경과 ${age} · ${overall}. ${benefit}. 접수 ${period}. 문의 건축안전센터`
      : `[${gov} 건축안전센터] ${address} 건축물이 ${program} 1차 ${overall}입니다. ${benefit}. 접수 ${period}. 이 문자는 초안입니다.`;
  }

  if (tone === "official") {
    return `${gov} 건축안전센터

「${program}」 안내문(초안)

수신: 건축물 소유자(관리자) 귀하
발신: ${gov} 건축안전센터

1. 대상 건축물
   - 주소: ${address}
   - 용도: ${use}
   - 사용승인일: ${approved}
   - 경과연수: ${age}
   - 1차 판정: ${overall}

2. 안내
   ${benefit}로 검토되었습니다. ${alt ? "최종 선정은 현장 확인 및 위원회 심사 결과에 따릅니다." : "이 안내는 최종 선정 통지가 아닙니다."}

3. 접수기간
   ${period}

4. 문의
   ${gov} 건축안전센터
   (시스템 생성 초안 · 발송 전 담당자 검수)

끝.`;
  }

  return alt
    ? `안녕하세요, ${gov} 건축안전센터입니다.

${address}에 있는 건물(${use}, 사용승인 ${approved}, 경과 ${age})이 ${program} 1차 검토에서 ${overall}로 나왔습니다.

${benefit}입니다. 접수기간은 ${period}이니, 편한 방법으로 센터에 문의해 주세요.

이 글은 초안이며 담당자가 확인한 뒤에 보내 드립니다.`
    : `안녕하세요. ${address}에 사시는 건물 소유자님께 알려 드립니다.

구청에서 하는 ${program} 안내입니다.
- 용도: ${use}
- 사용승인일: ${approved} (경과 ${age})
- 1차 검토: ${overall}

${benefit}입니다. 접수기간은 ${period}이에요. 자세한 내용은 ${gov} 건축안전센터로 문의해 주세요.

이 글은 시스템 초안입니다. 발송 전에 담당자가 한번 더 확인합니다.`;
}
