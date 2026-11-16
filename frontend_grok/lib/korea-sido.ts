/** Schematic sido polygons (lat, lng) for a country-scale choropleth. Smaller cities are drawn last. */

export type SidoRegion = {
  id: string;
  name: string;
  aliases: string[];
  center: [number, number];
  ring: [number, number][];
};

export const KOREA_SIDO: SidoRegion[] = [
  {
    id: "gangwon",
    name: "강원특별자치도",
    aliases: ["강원특별자치도", "강원도", "강원"],
    center: [37.82, 128.16],
    ring: [
      [38.62, 127.1],
      [38.58, 129.35],
      [37.05, 129.3],
      [37.05, 127.08],
    ],
  },
  {
    id: "gyeonggi",
    name: "경기도",
    aliases: ["경기도", "경기"],
    center: [37.4, 127.25],
    ring: [
      [38.28, 126.55],
      [38.28, 127.85],
      [36.9, 127.85],
      [36.9, 126.55],
    ],
  },
  {
    id: "chungbuk",
    name: "충청북도",
    aliases: ["충청북도", "충북"],
    center: [36.64, 127.49],
    ring: [
      [37.22, 127.7],
      [37.15, 128.62],
      [36.65, 128.55],
      [36.65, 127.7],
    ],
  },
  {
    id: "gyeongbuk",
    name: "경상북도",
    aliases: ["경상북도", "경북"],
    center: [36.49, 128.89],
    ring: [
      [37.55, 127.85],
      [37.55, 129.58],
      [35.72, 129.58],
      [35.72, 127.85],
    ],
  },
  {
    id: "chungnam",
    name: "충청남도",
    aliases: ["충청남도", "충남"],
    center: [36.52, 126.8],
    ring: [
      [37.05, 125.96],
      [37.05, 127.1],
      [36.0, 127.1],
      [35.98, 126.0],
    ],
  },
  {
    id: "jeonbuk",
    name: "전북특별자치도",
    aliases: ["전북특별자치도", "전라북도", "전북"],
    center: [35.82, 127.11],
    ring: [
      [36.0, 126.33],
      [36.0, 127.1],
      [35.3, 127.92],
      [35.3, 126.4],
    ],
  },
  {
    id: "jeonnam",
    name: "전라남도",
    aliases: ["전라남도", "전남"],
    center: [34.82, 126.46],
    ring: [
      [35.45, 125.45],
      [35.5, 127.6],
      [34.6, 127.85],
      [33.95, 126.9],
      [34.2, 125.1],
      [34.8, 125.05],
    ],
  },
  {
    id: "gyeongnam",
    name: "경상남도",
    aliases: ["경상남도", "경남"],
    center: [35.46, 128.21],
    ring: [
      [35.8, 127.6],
      [35.8, 129.2],
      [34.55, 129.2],
      [34.55, 127.75],
    ],
  },
  {
    id: "incheon",
    name: "인천광역시",
    aliases: ["인천광역시", "인천"],
    center: [37.46, 126.71],
    ring: [
      [37.75, 126.22],
      [37.65, 126.78],
      [37.25, 126.78],
      [37.3, 126.22],
    ],
  },
  {
    id: "seoul",
    name: "서울특별시",
    aliases: ["서울특별시", "서울"],
    center: [37.57, 126.98],
    ring: [
      [37.7, 126.78],
      [37.7, 127.18],
      [37.43, 127.18],
      [37.43, 126.78],
    ],
  },
  {
    id: "sejong",
    name: "세종특별자치시",
    aliases: ["세종특별자치시", "세종시", "세종"],
    center: [36.72, 127.2],
    ring: [
      [36.82, 127.0],
      [36.82, 127.28],
      [36.64, 127.28],
      [36.64, 127.0],
    ],
  },
  {
    id: "daejeon",
    name: "대전광역시",
    aliases: ["대전광역시", "대전"],
    center: [36.32, 127.4],
    ring: [
      [36.62, 127.12],
      [36.62, 127.7],
      [36.02, 127.7],
      [36.02, 127.12],
    ],
  },
  {
    id: "gwangju",
    name: "광주광역시",
    aliases: ["광주광역시", "광주"],
    center: [35.16, 126.85],
    ring: [
      [35.26, 126.7],
      [35.26, 126.96],
      [35.06, 126.96],
      [35.06, 126.7],
    ],
  },
  {
    id: "daegu",
    name: "대구광역시",
    aliases: ["대구광역시", "대구"],
    center: [35.87, 128.6],
    ring: [
      [35.99, 128.43],
      [35.99, 128.77],
      [35.77, 128.77],
      [35.77, 128.43],
    ],
  },
  {
    id: "ulsan",
    name: "울산광역시",
    aliases: ["울산광역시", "울산"],
    center: [35.54, 129.31],
    ring: [
      [35.72, 129.08],
      [35.72, 129.48],
      [35.32, 129.48],
      [35.32, 129.08],
    ],
  },
  {
    id: "busan",
    name: "부산광역시",
    aliases: ["부산광역시", "부산"],
    center: [35.18, 129.08],
    ring: [
      [35.4, 128.82],
      [35.4, 129.3],
      [34.95, 129.3],
      [34.95, 128.82],
    ],
  },
  {
    id: "jeju",
    name: "제주특별자치도",
    aliases: ["제주특별자치도", "제주도", "제주"],
    center: [33.39, 126.55],
    ring: [
      [33.56, 126.16],
      [33.56, 126.97],
      [33.18, 126.97],
      [33.22, 126.16],
    ],
  },
];

export function matchSido(text: string): SidoRegion | undefined {
  const t = text.replace(/\s+/g, "");
  if (!t) return undefined;
  const ranked = [...KOREA_SIDO].sort((a, b) => b.name.length - a.name.length);
  return ranked.find((r) => r.aliases.some((a) => t.includes(a.replace(/\s+/g, ""))));
}
