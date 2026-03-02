export default function HomePage() {
  return (
    <main className="page">
      <div className="card">
        <h1>Telegram REST API SaaS</h1>
        <p>
          Этот проект поднимает REST API поверх Telegram через Telethon и
          предоставляет основу для мультиаккаунтного SaaS‑клиента.
        </p>
        <ul>
          <li>Авторизация по номеру телефона и QR‑коду</li>
          <li>Управление чатами, сообщениями, каналами и контактами</li>
          <li>Планируется мультисессионный режим через Supabase</li>
        </ul>
        <p className="hint">
          Backend доступен по адресу <code>http://localhost:8000</code>, а эта
          страница — стартовая точка фронтенда.
        </p>
      </div>
    </main>
  );
}

