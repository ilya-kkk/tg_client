"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import styles from "./channels-parser.module.css";

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

interface ChannelsSearchResultItem {
  channel_id: string;
  title: string;
  username: string | null;
  link: string | null;
  about: string | null;
  participants_count: number | null;
  verified: boolean | null;
  scam: boolean | null;
  fake: boolean | null;
  found_by: string[];
}

interface ChannelsSearchResponse {
  items: ChannelsSearchResultItem[];
  total: number;
}

interface SaveParsedChannelsResponse {
  success: boolean;
  saved: number;
  message: string;
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

function parseKeywords(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function toCsv(items: ChannelsSearchResultItem[]): string {
  const header = ["title", "username", "link", "participants", "found_by"];
  const rows = items.map((item) => [
    item.title,
    item.username ? `@${item.username}` : "",
    item.link ?? "",
    item.participants_count?.toString() ?? "",
    item.found_by.join("|")
  ]);

  const allRows = [header, ...rows];
  return allRows
    .map((row) =>
      row
        .map((value) => `"${value.replaceAll('"', '""')}"`)
        .join(",")
    )
    .join("\n");
}

function download(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ChannelsParserPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [keywordsText, setKeywordsText] = useState<string>("crypto\nmarketing");
  const [limitPerKeyword, setLimitPerKeyword] = useState<number>(20);
  const [includeAbout, setIncludeAbout] = useState<boolean>(true);

  const [items, setItems] = useState<ChannelsSearchResultItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const response = await fetchJson<SessionsResponse>(`${API_BASE}/sessions`);
      const authorized = response.sessions.filter((session) => session.is_authorized);
      setSessions(authorized);
      if (!sessionId && authorized.length > 0) {
        setSessionId(authorized[0].session_id);
      }
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось загрузить список сессий");
      }
    }
  }, [sessionId]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const canSearch = useMemo(() => {
    const keywords = parseKeywords(keywordsText);
    return Boolean(sessionId) && keywords.length > 0 && !loading;
  }, [keywordsText, loading, sessionId]);

  const runSearch = useCallback(async () => {
    const keywords = parseKeywords(keywordsText);
    if (!sessionId) {
      setError("Выберите session_id");
      return;
    }
    if (keywords.length === 0) {
      setError("Добавьте хотя бы одно ключевое слово");
      return;
    }

    setLoading(true);
    setSaveMessage(null);
    setError(null);

    try {
      const response = await fetchJson<ChannelsSearchResponse>(
        `${API_BASE}/sessions/${sessionId}/channels/search`,
        {
          method: "POST",
          body: JSON.stringify({
            keywords,
            limit_per_keyword: limitPerKeyword,
            include_about: includeAbout,
            language: null
          })
        }
      );
      setItems(response.items);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось выполнить поиск каналов");
      }
    } finally {
      setLoading(false);
    }
  }, [includeAbout, keywordsText, limitPerKeyword, sessionId]);

  const saveToDatabase = useCallback(async () => {
    if (!sessionId || items.length === 0) {
      return;
    }

    setSaving(true);
    setSaveMessage(null);
    setError(null);

    try {
      const response = await fetchJson<SaveParsedChannelsResponse>(
        `${API_BASE}/sessions/${sessionId}/channels/parsed`,
        {
          method: "POST",
          body: JSON.stringify({ items })
        }
      );
      setSaveMessage(`Сохранено записей: ${response.saved}`);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось сохранить результаты");
      }
    } finally {
      setSaving(false);
    }
  }, [items, sessionId]);

  const exportCsv = useCallback(() => {
    if (items.length === 0) {
      return;
    }
    const csv = toCsv(items);
    download("channels.csv", csv, "text/csv;charset=utf-8");
  }, [items]);

  const exportTxt = useCallback(() => {
    if (items.length === 0) {
      return;
    }
    const usernames = items
      .map((item) => item.username)
      .filter((username): username is string => Boolean(username))
      .map((username) => `@${username}`);
    download("usernames.txt", usernames.join("\n"), "text/plain;charset=utf-8");
  }, [items]);

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Парсер каналов</h1>
      </div>

      <div className={styles.card}>
        <div className={styles.form}>
          <div>
            <label className={styles.label} htmlFor="sessionId">
              Сессия
            </label>
            <select
              id="sessionId"
              className={styles.input}
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value)}
            >
              {sessions.length === 0 && <option value="">Нет авторизованных сессий</option>}
              {sessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_id}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={styles.label} htmlFor="keywords">
              Ключевые слова (по одному на строку)
            </label>
            <textarea
              id="keywords"
              className={styles.textarea}
              rows={6}
              value={keywordsText}
              onChange={(event) => setKeywordsText(event.target.value)}
            />
          </div>

          <div className={styles.row}>
            <div>
              <label className={styles.label} htmlFor="limitPerKeyword">
                Лимит на ключевое слово
              </label>
              <input
                id="limitPerKeyword"
                type="number"
                min={1}
                max={100}
                className={styles.input}
                value={limitPerKeyword}
                onChange={(event) => setLimitPerKeyword(Number(event.target.value))}
              />
            </div>
            <label className={styles.checkboxRow} htmlFor="includeAbout">
              <input
                id="includeAbout"
                type="checkbox"
                checked={includeAbout}
                onChange={(event) => setIncludeAbout(event.target.checked)}
              />
              Тянуть описание канала
            </label>
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.button}
              onClick={() => void runSearch()}
              disabled={!canSearch}
            >
              {loading ? "Поиск..." : "Запустить поиск"}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => void saveToDatabase()}
              disabled={loading || saving || items.length === 0}
            >
              {saving ? "Сохранение..." : "Сохранить в базу"}
            </button>
            <button
              type="button"
              className={styles.ghostButton}
              onClick={exportCsv}
              disabled={items.length === 0}
            >
              Скачать CSV
            </button>
            <button
              type="button"
              className={styles.ghostButton}
              onClick={exportTxt}
              disabled={items.length === 0}
            >
              Сохранить @username в TXT
            </button>
          </div>
        </div>
      </div>

      {loading && <div className={styles.state}>Загрузка результатов...</div>}

      {error && <div className={`${styles.state} ${styles.error}`}>{error}</div>}

      {saveMessage && <div className={styles.state}>{saveMessage}</div>}

      {!loading && !error && items.length === 0 && (
        <div className={styles.state}>Результатов пока нет. Запустите поиск.</div>
      )}

      {!loading && items.length > 0 && (
        <div className={`${styles.card} ${styles.tableWrap}`}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Название</th>
                <th>Username</th>
                <th>Подписчики</th>
                <th>Найден по</th>
                <th>Ссылка</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.channel_id}>
                  <td>{item.title}</td>
                  <td>{item.username ? `@${item.username}` : <span className={styles.muted}>-</span>}</td>
                  <td>{item.participants_count ?? <span className={styles.muted}>-</span>}</td>
                  <td>{item.found_by.join(", ")}</td>
                  <td>
                    {item.link ? (
                      <a href={item.link} target="_blank" rel="noreferrer">
                        открыть
                      </a>
                    ) : (
                      <span className={styles.muted}>-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
