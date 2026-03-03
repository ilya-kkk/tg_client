"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import styles from "./warmup.module.css";

const API_BASE = "http://localhost:8000";
const STORAGE_USER_ID_KEY = "tg_client_user_id";

type WarmupMode = "cautious" | "normal" | "aggressive";

interface WarmupJob {
  id: string;
  user_id: string;
  name: string;
  account_sessions: string[];
  mode: WarmupMode;
  actions_per_day: number;
  enabled_actions: string[];
  target_channels: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

const MODE_LABELS: Record<WarmupMode, string> = {
  cautious: "Осторожный",
  normal: "Нормальный",
  aggressive: "Агрессивный"
};

const MODE_BADGE_CLASSES: Record<WarmupMode, string> = {
  cautious: "modeCautious",
  normal: "modeNormal",
  aggressive: "modeAggressive"
};

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

export default function WarmupPage() {
  const [userId, setUserId] = useState<string | null | undefined>(undefined);
  const [jobs, setJobs] = useState<WarmupJob[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = useCallback(async (targetUserId: string) => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetchJson<WarmupJob[]>(`${API_BASE}/users/${targetUserId}/warmup-jobs`);
      setJobs(response);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось загрузить кампании прогрева");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(STORAGE_USER_ID_KEY);
    setUserId(savedUserId);
  }, []);

  useEffect(() => {
    if (userId === undefined) {
      return;
    }

    if (!userId) {
      setJobs([]);
      setError(null);
      setLoading(false);
      return;
    }

    void loadJobs(userId);
  }, [loadJobs, userId]);

  const sortedJobs = useMemo(() => [...jobs].sort((a, b) => a.name.localeCompare(b.name)), [jobs]);

  const toggleLocalActive = useCallback((jobId: string) => {
    setJobs((prev) =>
      prev.map((job) => (job.id === jobId ? { ...job, is_active: !job.is_active } : job))
    );
  }, []);

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Прогрев аккаунтов</h1>
        <button type="button" className={styles.createButton}>
          + Создать кампанию
        </button>
      </div>

      {loading && (
        <div className={styles.skeletonList}>
          <div className={styles.skeletonCard} />
          <div className={styles.skeletonCard} />
          <div className={styles.skeletonCard} />
        </div>
      )}

      {!loading && error && (
        <div className={styles.errorState}>
          <p>{error}</p>
          <button
            type="button"
            className={styles.retryButton}
            onClick={() => {
              if (userId) {
                void loadJobs(userId);
              }
            }}
            disabled={!userId}
          >
            Повторить
          </button>
        </div>
      )}

      {!loading && !error && sortedJobs.length === 0 && (
        <div className={styles.emptyState}>Нет кампаний прогрева. Создайте первую!</div>
      )}

      {!loading && !error && sortedJobs.length > 0 && (
        <div className={styles.cardsList}>
          {sortedJobs.map((job) => (
            <article key={job.id} className={styles.card}>
              <div className={styles.leftBlock}>
                <h2 className={styles.cardTitle}>{job.name}</h2>
                <span className={`${styles.modeBadge} ${styles[MODE_BADGE_CLASSES[job.mode]]}`}>
                  {MODE_LABELS[job.mode]}
                </span>
              </div>

              <div className={styles.rightBlock}>
                <span className={styles.accountCounter}>{job.account_sessions.length} аккаунтов</span>

                <button type="button" className={styles.iconButton} aria-label="Редактировать кампанию">
                  ✏️
                </button>

                <button
                  type="button"
                  className={styles.iconButtonDanger}
                  aria-label="Удалить кампанию"
                >
                  🗑️
                </button>

                <label className={styles.toggleWrap}>
                  <input
                    type="checkbox"
                    className={styles.toggleInput}
                    checked={job.is_active}
                    onChange={() => toggleLocalActive(job.id)}
                  />
                  <span className={styles.toggleSlider} aria-hidden="true" />
                  <span className={styles.toggleLabel}>{job.is_active ? "Вкл" : "Выкл"}</span>
                </label>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
