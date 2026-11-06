import type { BuildingRecord, Extracted } from "./types";
import { flat } from "./download";

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
