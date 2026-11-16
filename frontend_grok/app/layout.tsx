import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "소규모 노후건축물 안전점검 지원 대상 선별 시스템",
  description: "구청 건축안전센터 담당자를 위한 공고 조건 추출·1차 판정·안내문 작성 화면입니다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
