"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import styles from "./auto-reactions.module.css";

const API_BASE = "http://localhost:8000";
const STORAGE_USER_ID_KEY = "tg_client_user_id";
const CHATS_FETCH_LIMIT = 1000;
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

interface ChatInfo {
  id: number;
  name: string;
  type: string | null;
  username: string | null;
}

interface ChatsResponse {
  success: boolean;
  chats: ChatInfo[];
  total: number;
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
  target_chats: string[];
}

interface ChatOption {
  value: string;
  label: string;
}

const INITIAL_FORM: JobFormState = {
  name: "",
  account_sessions: [],
  reactions: ["👍"],
  message_frequency: "every",
  target_chats: []
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

function toForm(job: ReactionJob): JobFormState {
  return {
    name: job.name,
    account_sessions: [...job.account_sessions],
    reactions: [...job.reactions],
    message_frequency: job.message_frequency,
    target_chats: [...job.target_chats]
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
  const [availableChats, setAvailableChats] = useState<ChatOption[]>([]);
  const [loadingChats, setLoadingChats] = useState<boolean>(false);
  const [chatsError, setChatsError] = useState<string | null>(null);

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

  const loadAvailableChats = useCallback(async (sessionIds: string[]) => {
    if (sessionIds.length === 0) {
      setAvailableChats([]);
      setChatsError(null);
      setLoadingChats(false);
      setForm((prev) => ({ ...prev, target_chats: [] }));
      return;
    }

    setLoadingChats(true);
    setChatsError(null);

    try {
      const settled = await Promise.allSettled(
        sessionIds.map((sessionId) =>
          fetchJson<ChatsResponse>(
            `${API_BASE}/sessions/${sessionId}/chats?limit=${CHATS_FETCH_LIMIT}`
          )
        )
      );

      const successItems = settled
        .filter((entry): entry is PromiseFulfilledResult<ChatsResponse> => entry.status === "fulfilled")
        .map((entry) => entry.value);

      if (successItems.length === 0) {
        const firstError = settled.find((entry): entry is PromiseRejectedResult => entry.status === "rejected");
        throw new Error(firstError?.reason?.message ?? "Не удалось загрузить чаты выбранных аккаунтов");
      }

      const chatMap = new Map<string, ChatOption>();

      for (const response of successItems) {
        for (const chat of response.chats) {
          const value = chat.username ? `@${chat.username}` : String(chat.id);
          if (chatMap.has(value)) {
            continue;
          }

          const safeName = chat.name?.trim() ? chat.name : value;
          const label = chat.username ? `${safeName} (${value})` : `${safeName} (id: ${chat.id})`;
          chatMap.set(value, { value, label });
        }
      }

      const mergedOptions = Array.from(chatMap.values()).sort((a, b) => a.label.localeCompare(b.label));
      setAvailableChats(mergedOptions);

      const allowed = new Set(mergedOptions.map((item) => item.value));
      setForm((prev) => ({
        ...prev,
        target_chats: prev.target_chats.filter((chat) => allowed.has(chat))
      }));

      if (successItems.length !== sessionIds.length) {
        setChatsError("Часть аккаунтов не удалось загрузить. Показаны доступные чаты.");
      }
    } catch (e: unknown) {
      setAvailableChats([]);
      setForm((prev) => ({ ...prev, target_chats: [] }));
      if (e instanceof Error) {
        setChatsError(e.message);
      } else {
        setChatsError("Не удалось загрузить чаты выбранных аккаунтов");
      }
    } finally {
      setLoadingChats(false);
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
    setAvailableChats([]);
    setChatsError(null);
    setLoadingChats(false);
  }, [saving]);

  const submitModal = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!userId) {
      setError("Пользователь не определен. Войдите заново.");
      return;
    }

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
    if (form.target_chats.length === 0) {
      setError("Выберите хотя бы один чат");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const payload: ReactionJobPayload = {
        name: form.name.trim(),
        account_sessions: form.account_sessions,
        reactions: form.reactions,
        message_frequency: form.message_frequency,
        target_chats: form.target_chats
      };

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

  const toggleTargetChat = useCallback((chatValue: string) => {
    setForm((prev) => {
      const exists = prev.target_chats.includes(chatValue);
      return {
        ...prev,
        target_chats: exists
          ? prev.target_chats.filter((item) => item !== chatValue)
          : [...prev.target_chats, chatValue]
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
      setError("Пользователь не определен. Войдите заново.");
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
      setError("Пользователь не определен. Войдите заново.");
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

  useEffect(() => {
    if (!isModalOpen) {
      return;
    }
    void loadAvailableChats(form.account_sessions);
  }, [form.account_sessions, isModalOpen, loadAvailableChats]);

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
          <button
            type="button"
            className={styles.secondaryButton}
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
                <label className={styles.toggleWrap}>
                  <input
                    type="checkbox"
                    className={styles.toggleInput}
                    checked={job.is_active}
                    onChange={() => void toggleJobActive(job)}
                    disabled={togglingJobId === job.id}
                  />
                  <span
                    className={`${styles.toggleSlider} ${
                      togglingJobId === job.id ? styles.toggleSliderLoading : ""
                    }`}
                    aria-hidden="true"
                  >
                    {togglingJobId === job.id && <span className={styles.toggleSpinner} />}
                  </span>
                  <span className={styles.toggleLabel}>{job.is_active ? "Вкл" : "Выкл"}</span>
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
                <p className={styles.label}>Чаты для мониторинга</p>
                {loadingChats && <p className={styles.subtitle}>Загрузка чатов...</p>}
                {!loadingChats && chatsError && <p className={styles.subtitle}>{chatsError}</p>}
                {!loadingChats && !chatsError && availableChats.length === 0 && (
                  <p className={styles.subtitle}>Нет доступных чатов для выбранных аккаунтов.</p>
                )}
                {!loadingChats && availableChats.length > 0 && (
                  <div className={styles.gridOptions}>
                    {availableChats.map((chat) => (
                      <label key={chat.value} className={styles.checkboxLabel}>
                        <input
                          type="checkbox"
                          checked={form.target_chats.includes(chat.value)}
                          onChange={() => toggleTargetChat(chat.value)}
                        />
                        <span>{chat.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div className={styles.modalActions}>
                <button type="submit" className={styles.createButton} disabled={saving || loadingChats}>
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
