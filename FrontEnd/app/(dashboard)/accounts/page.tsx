"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AddAccountModal from "./AddAccountModal";
import styles from "./accounts.module.css";

const API_BASE = "http://localhost:8000";

interface SessionInfo {
  session_id: string;
  phone: string | null;
  is_authorized: boolean;
}

interface SessionsResponse {
  success: boolean;
  sessions: SessionInfo[];
  total: number;
}

interface AccountInfo {
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  phone: string | null;
  photo?: string | null;
}

interface AccountInfoResponse {
  success: boolean;
  account: AccountInfo;
}

interface AccountCard extends AccountInfo {
  session_id: string;
}

function normalizePhoto(photo: string | null | undefined): string | null {
  if (!photo) {
    return null;
  }
  if (
    photo.startsWith("http://") ||
    photo.startsWith("https://") ||
    photo.startsWith("data:")
  ) {
    return photo;
  }
  return `data:image/jpeg;base64,${photo}`;
}

function buildFullName(account: AccountInfo): string {
  const parts = [account.first_name, account.last_name].filter(Boolean);
  if (parts.length > 0) {
    return parts.join(" ");
  }
  return account.username ? `@${account.username}` : "Без имени";
}

function buildInitials(account: AccountInfo): string {
  const first = account.first_name?.trim().charAt(0) ?? "";
  const last = account.last_name?.trim().charAt(0) ?? "";
  if (first || last) {
    return `${first}${last}`.toUpperCase();
  }
  if (account.username) {
    return account.username.slice(0, 2).toUpperCase();
  }
  return "?";
}

function colorFromName(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 62%, 44%)`;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody?.detail ?? errorBody?.message ?? `Ошибка запроса (${response.status})`;
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const sessionsResponse = await fetchJson<SessionsResponse>(`${API_BASE}/sessions`);
      const authorizedSessions = sessionsResponse.sessions.filter(
        (session) => session.is_authorized
      );

      if (authorizedSessions.length === 0) {
        setAccounts([]);
        return;
      }

      const result = await Promise.allSettled(
        authorizedSessions.map(async (session): Promise<AccountCard> => {
          const accountResponse = await fetchJson<AccountInfoResponse>(
            `${API_BASE}/sessions/${session.session_id}/account/me`
          );

          return {
            session_id: session.session_id,
            ...accountResponse.account,
            phone: accountResponse.account.phone ?? session.phone
          };
        })
      );

      const nextAccounts: AccountCard[] = result
        .filter(
          (entry): entry is PromiseFulfilledResult<AccountCard> =>
            entry.status === "fulfilled"
        )
        .map((entry) => entry.value);

      setAccounts(nextAccounts);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось загрузить аккаунты");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const sortedAccounts = useMemo(
    () => [...accounts].sort((a, b) => buildFullName(a).localeCompare(buildFullName(b))),
    [accounts]
  );

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Аккаунты</h1>
        <button
          type="button"
          className={styles.addButton}
          onClick={() => setIsModalOpen(true)}
        >
          Добавить аккаунт
        </button>
      </div>

      {loading && <div className={styles.state}>Загрузка...</div>}

      {!loading && error && (
        <div className={styles.stateError}>
          <p>{error}</p>
          <button type="button" className={styles.retryButton} onClick={() => void loadAccounts()}>
            Повторить
          </button>
        </div>
      )}

      {!loading && !error && sortedAccounts.length === 0 && (
        <div className={styles.state}>Нет аккаунтов</div>
      )}

      {!loading && !error && sortedAccounts.length > 0 && (
        <div className={styles.grid}>
          {sortedAccounts.map((account) => {
            const fullName = buildFullName(account);
            const initials = buildInitials(account);
            const photoSrc = normalizePhoto(account.photo);

            return (
              <article key={account.session_id} className={styles.card}>
                <div
                  className={styles.avatar}
                  style={{ backgroundColor: colorFromName(fullName) }}
                  aria-label={`Аватар ${fullName}`}
                >
                  {photoSrc ? (
                    <img className={styles.avatarImage} src={photoSrc} alt={fullName} />
                  ) : (
                    <span>{initials}</span>
                  )}
                </div>

                <div className={styles.meta}>
                  <h2 className={styles.name}>{fullName}</h2>
                  <p className={styles.phone}>{account.phone ?? "Телефон не указан"}</p>
                  <p className={styles.username}>
                    {account.username ? `@${account.username}` : "Без username"}
                  </p>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <AddAccountModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={() => loadAccounts()}
      />
    </section>
  );
}
