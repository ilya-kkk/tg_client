import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Telegram REST API Frontend",
  description: "Минимальный фронтенд для SaaS над Telegram REST API"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}

