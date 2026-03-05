import type { ReactNode } from "react";
import Link from "next/link";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <h2 className="sidebar-title">Меню</h2>
        <nav className="sidebar-nav">
          <Link href="/home" className="nav-link">
            Домашняя
          </Link>
          <Link href="/accounts" className="nav-link">
            Аккаунты
          </Link>
          <Link href="/channels-parser" className="nav-link">
            Парсер каналов
          </Link>
          <Link href="/auto-reactions" className="nav-link">
            Автореакции
          </Link>
          <Link href="/ai-commenting" className="nav-link">
            Нейрокомментарии
          </Link>
          <Link href="/warmup" className="nav-link">
            Прогрев
          </Link>
        </nav>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
