"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import styles from "./auto-reactions.module.css";

const API_BASE = "http://localhost:8000";
const STORAGE_USER_ID_KEY = "tg_client_user_id";
const POPULAR_REACTIONS = ["👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "💯", "🎉"] as const;

type MessageFrequency = "every" | "1/2" | "1/3" | "2/3";

interface ReactionJob {
  id: string;
  user_id: string;
  name: string;
  account_sessions: string[];
  reactions: string[];
  message_frequency: MessageFrequency;
  target_chats: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

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
}

interface AccountInfoResponse {
  success: boolean;
  account: AccountInfo;
}

interface SessionOption {
  session_id: string;
  label: string;
}

interface ReactionJobPayload {
  name: string;
  account_sessions: string[];
  reactions: string[];
  message_frequency: MessageFrequency;
  target_chats: string[];
}

interface JobFormState {
  name: string;
  account_sessions: string[];
  reactions: string[];
  message_frequency: MessageFrequency;
  target_chats_text: string;
}

const INITIAL_FORM: JobFormState = {
  name: "",
  account_sessions: [],
  reactions: ["👍"],
  message_frequency: "every",
  target_chats_text: ""
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

function buildAccountLabel(account: AccountInfo | null, fallbackPhone: string | null, sessionId: string): string {
  if (account) {
    const fullName = [account.first_name, account.last_name].filter(Boolean).join(" ").trim();
    if (fullName) {
      return fullName;
    }
    if (account.username) {
      return `@${account.username}`;
    }
    if (account.phone) {
      return account.phone;
    }
  }

  if (fallbackPhone) {
    return fallbackPhone;
  }

  return sessionId;
}

function parseTargetChats(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function toForm(job: ReactionJob): JobFormState {
  return {
    name: job.name,
    account_sessions: [...job.account_sessions],
    reactions: [...job.reactions],
    message_frequency: job.message_frequency,
    target_chats_text: job.target_chats.join("\n")
  };
}

export default function AutoReactionsPage() {
  const [userId, setUserId] = useState<string>("");
  const [jobs, setJobs] = useState<ReactionJob[]>([]);
  const [sessions, setSessions] = useState<SessionOption[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [togglingJobId, setTogglingJobId] = useState<string | null>(null);

  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingJob, setEditingJob] = useState<ReactionJob | null>(null);
  const [form, setForm] = useState<JobFormState>(INITIAL_FORM);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_USER_ID_KEY);
    if (saved) {
      setUserId(saved);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    const response = await fetchJson<SessionsResponse>(`${API_BASE}/sessions`);
    const authorized = response.sessions.filter((session) => session.is_authorized);

    const results = await Promise.allSettled(
      authorized.map(async (session): Promise<SessionOption> => {
        const info = await fetchJson<AccountInfoResponse>(
          `${API_BASE}/sessions/${session.session_id}/account/me`
        );
        return {
          session_id: session.session_id,
          label: buildAccountLabel(info.account, session.phone, session.session_id)
        };
      })
    );

    const options = results.map((result, index) => {
      const session = authorized[index];
      if (result.status === "fulfilled") {
        return result.value;
      }
      return {
        session_id: session.session_id,
        label: buildAccountLabel(null, session.phone, session.session_id)
      };
    });

    setSessions(options);
  }, []);

  const loadJobs = useCallback(async (targetUserId: string) => {
    if (!targetUserId) {
      setJobs([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetchJson<ReactionJob[]>(
        `${API_BASE}/users/${targetUserId}/reaction-jobs`
      );
      setJobs(response);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось загрузить кампании");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      return;
    }
    void loadJobs(userId);
  }, [loadJobs, userId]);

  const openCreateModal = useCallback(() => {
    setEditingJob(null);
    setForm(INITIAL_FORM);
    setIsModalOpen(true);
  }, []);

  const openEditModal = useCallback((job: ReactionJob) => {
    setEditingJob(job);
    setForm(toForm(job));
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingJob(null);
  }, [saving]);

  const submitModal = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!userId) {
      setError("Укажите user_id");
      return;
    }

    const targetChats = parseTargetChats(form.target_chats_text);
    if (!form.name.trim()) {
      setError("Введите название кампании");
      return;
    }
    if (form.account_sessions.length === 0) {
      setError("Выберите хотя бы один аккаунт");
      return;
    }
    if (form.reactions.length === 0) {
      setError("Выберите хотя бы одну реакцию");
      return;
    }
    if (targetChats.length === 0) {
      setError("Добавьте хотя бы один чат");
      return;
    }

    const payload: ReactionJobPayload = {
      name: form.name.trim(),
      account_sessions: form.account_sessions,
      reactions: form.reactions,
      message_frequency: form.message_frequency,
      target_chats: targetChats
    };

    setSaving(true);
    setError(null);

    try {
      if (editingJob) {
        const updated = await fetchJson<ReactionJob>(
          `${API_BASE}/users/${userId}/reaction-jobs/${editingJob.id}`,
          {
            method: "PATCH",
            body: JSON.stringify(payload)
          }
        );
        setJobs((prev) => prev.map((job) => (job.id === updated.id ? updated : job)));
      } else {
        const created = await fetchJson<ReactionJob>(`${API_BASE}/users/${userId}/reaction-jobs`, {
          method: "POST",
          body: JSON.stringify(payload)
        });
        setJobs((prev) => [...prev, created]);
      }

      setIsModalOpen(false);
      setEditingJob(null);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось сохранить кампанию");
      }
    } finally {
      setSaving(false);
    }
  }, [editingJob, form, userId]);

  const toggleAccountSession = useCallback((sessionId: string) => {
    setForm((prev) => {
      const exists = prev.account_sessions.includes(sessionId);
      return {
        ...prev,
        account_sessions: exists
          ? prev.account_sessions.filter((id) => id !== sessionId)
          : [...prev.account_sessions, sessionId]
      };
    });
  }, []);

  const toggleReaction = useCallback((reaction: string) => {
    setForm((prev) => {
      const exists = prev.reactions.includes(reaction);
      const next = exists ? prev.reactions.filter((item) => item !== reaction) : [...prev.reactions, reaction];
      return {
        ...prev,
        reactions: next
      };
    });
  }, []);

  const toggleJobActive = useCallback(async (job: ReactionJob) => {
    if (!userId) {
      setError("Укажите user_id");
      return;
    }

    const nextValue = !job.is_active;
    setTogglingJobId(job.id);
    setError(null);
    setJobs((prev) => prev.map((item) => (item.id === job.id ? { ...item, is_active: nextValue } : item)));

    try {
      const updated = await fetchJson<ReactionJob>(
        `${API_BASE}/users/${userId}/reaction-jobs/${job.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ is_active: nextValue })
        }
      );
      setJobs((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (e: unknown) {
      setJobs((prev) => prev.map((item) => (item.id === job.id ? { ...item, is_active: job.is_active } : item)));
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось изменить статус кампании");
      }
    } finally {
      setTogglingJobId(null);
    }
  }, [userId]);

  const removeJob = useCallback(async (job: ReactionJob) => {
    if (!userId) {
      setError("Укажите user_id");
      return;
    }

    const confirmed = window.confirm(`Удалить кампанию «${job.name}»?`);
    if (!confirmed) {
      return;
    }

    setDeletingJobId(job.id);
    setError(null);
    try {
      await fetchJson<{ success: boolean }>(`${API_BASE}/users/${userId}/reaction-jobs/${job.id}`, {
        method: "DELETE"
      });
      setJobs((prev) => prev.filter((item) => item.id !== job.id));
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось удалить кампанию");
      }
    } finally {
      setDeletingJobId(null);
    }
  }, [userId]);

  const sortedJobs = useMemo(() => [...jobs].sort((a, b) => a.name.localeCompare(b.name)), [jobs]);

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Автореакции</h1>
          <p className={styles.subtitle}>Автоматическая реакция на новые сообщения в выбранных чатах</p>
        </div>
        <button type="button" className={styles.createButton} onClick={openCreateModal}>
          + Создать кампанию
        </button>
      </div>

      <div className={styles.userBox}>
        <label htmlFor="userId" className={styles.label}>User ID</label>
        <div className={styles.userRow}>
          <input
            id="userId"
            className={styles.input}
            value={userId}
            onChange={(event) => setUserId(event.target.value.trim())}
            placeholder="UUID пользователя Supabase"
          />
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => {
              window.localStorage.setItem(STORAGE_USER_ID_KEY, userId);
              void loadJobs(userId);
            }}
          >
            Применить
          </button>
        </div>
      </div>

      {loading && (
        <div className={styles.skeletonList}>
          <div className={styles.skeletonItem} />
          <div className={styles.skeletonItem} />
          <div className={styles.skeletonItem} />
        </div>
      )}

      {!loading && error && (
        <div className={styles.errorBox}>
          <p>{error}</p>
          <button type="button" className={styles.secondaryButton} onClick={() => void loadJobs(userId)}>
            Повторить
          </button>
        </div>
      )}

      {!loading && !error && sortedJobs.length === 0 && (
        <div className={styles.emptyState}>Нет кампаний. Создайте первую!</div>
      )}

      {!loading && !error && sortedJobs.length > 0 && (
        <div className={styles.list}>
          {sortedJobs.map((job) => (
            <article key={job.id} className={styles.row}>
              <div className={styles.rowName}>{job.name}</div>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() => openEditModal(job)}
                  aria-label="Редактировать"
                >
                  ✏️
                </button>
                <button
                  type="button"
                  className={styles.iconButtonDanger}
                  onClick={() => void removeJob(job)}
                  aria-label="Удалить"
                  disabled={deletingJobId === job.id}
                >
                  {deletingJobId === job.id ? "..." : "🗑️"}
                </button>
                <label className={styles.switchWrap}>
                  <input
                    type="checkbox"
                    checked={job.is_active}
                    onChange={() => void toggleJobActive(job)}
                    disabled={togglingJobId === job.id}
                  />
                  <span>{togglingJobId === job.id ? "..." : job.is_active ? "Вкл" : "Выкл"}</span>
                </label>
              </div>
            </article>
          ))}
        </div>
      )}

      {isModalOpen && (
        <div className={styles.modalOverlay} onClick={closeModal}>
          <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
            <h2 className={styles.modalTitle}>
              {editingJob ? "Редактировать кампанию" : "Создать кампанию"}
            </h2>

            <form className={styles.form} onSubmit={submitModal}>
              <div>
                <label className={styles.label} htmlFor="name">Название кампании</label>
                <input
                  id="name"
                  className={styles.input}
                  value={form.name}
                  onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  required
                />
              </div>

              <div>
                <p className={styles.label}>Аккаунты</p>
                <div className={styles.gridOptions}>
                  {sessions.map((session) => (
                    <label key={session.session_id} className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={form.account_sessions.includes(session.session_id)}
                        onChange={() => toggleAccountSession(session.session_id)}
                      />
                      <span>{session.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className={styles.label}>Реакции</p>
                <div className={styles.emojiGrid}>
                  {POPULAR_REACTIONS.map((reaction) => (
                    <label key={reaction} className={styles.emojiLabel}>
                      <input
                        type="checkbox"
                        checked={form.reactions.includes(reaction)}
                        onChange={() => toggleReaction(reaction)}
                      />
                      <span>{reaction}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className={styles.label}>Частота реакций</p>
                <div className={styles.radioGroup}>
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={form.message_frequency === "every"}
                      onChange={() => setForm((prev) => ({ ...prev, message_frequency: "every" }))}
                    />
                    <span>Каждое сообщение</span>
                  </label>
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={form.message_frequency === "1/2"}
                      onChange={() => setForm((prev) => ({ ...prev, message_frequency: "1/2" }))}
                    />
                    <span>Каждое 2-е</span>
                  </label>
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={form.message_frequency === "1/3"}
                      onChange={() => setForm((prev) => ({ ...prev, message_frequency: "1/3" }))}
                    />
                    <span>Каждое 3-е</span>
                  </label>
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={form.message_frequency === "2/3"}
                      onChange={() => setForm((prev) => ({ ...prev, message_frequency: "2/3" }))}
                    />
                    <span>2 из 3-х</span>
                  </label>
                </div>
              </div>

              <div>
                <label className={styles.label} htmlFor="target_chats">Чаты для мониторинга</label>
                <textarea
                  id="target_chats"
                  className={styles.textarea}
                  value={form.target_chats_text}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, target_chats_text: event.target.value }))
                  }
                  placeholder="@username\nt.me/channel_name"
                  rows={5}
                />
              </div>

              <div className={styles.modalActions}>
                <button type="submit" className={styles.createButton} disabled={saving}>
                  {saving ? "Сохранение..." : "Сохранить"}
                </button>
                <button type="button" className={styles.secondaryButton} onClick={closeModal} disabled={saving}>
                  Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
