import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "공고 조건 추출기",
  description: "소규모 노후 건축물 안전점검 공고문에서 지원 조건을 뽑습니다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
