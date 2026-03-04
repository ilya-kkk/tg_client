"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
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

interface WarmupJobPayload {
  name: string;
  account_sessions: string[];
  mode: WarmupMode;
  enabled_actions: string[];
  target_channels: string[];
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
  phone: string | null;
}

interface AccountInfoResponse {
  success: boolean;
  account: AccountInfo;
}

interface SessionOption {
  session_id: string;
  label: string;
  description: string;
}

interface FormState {
  name: string;
  mode: WarmupMode;
  account_sessions: string[];
  enabled_actions: string[];
  target_channels_input: string;
}

interface WarmupModeOption {
  value: WarmupMode;
  label: string;
  description: string;
  colorClass: string;
}

interface ActionOption {
  value: string;
  icon: string;
  title: string;
  description: string;
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

const MODE_OPTIONS: WarmupModeOption[] = [
  {
    value: "cautious",
    label: "Осторожный",
    description: "5–15 действий/день, длинные паузы",
    colorClass: "modeCardCautious"
  },
  {
    value: "normal",
    label: "Нормальный",
    description: "20–50 действий/день, умеренные паузы",
    colorClass: "modeCardNormal"
  },
  {
    value: "aggressive",
    label: "Агрессивный",
    description: "60–120 действий/день, короткие паузы",
    colorClass: "modeCardAggressive"
  }
];

const ACTION_OPTIONS: ActionOption[] = [
  {
    value: "read_messages",
    icon: "📖",
    title: "Чтение сообщений",
    description: "Открыть чат и прочитать несколько последних сообщений"
  },
  {
    value: "react_to_message",
    icon: "💬",
    title: "Реакция на сообщение",
    description: "Поставить случайную реакцию на сообщение в канале"
  },
  {
    value: "join_channel",
    icon: "➕",
    title: "Подписка на канал",
    description: "Подписаться на случайный канал из списка прогрева"
  },
  {
    value: "view_story",
    icon: "👀",
    title: "Просмотр историй",
    description: "Открыть истории случайного контакта или канала"
  },
  {
    value: "search_global",
    icon: "🔎",
    title: "Глобальный поиск",
    description: "Выполнить поиск по случайному нейтральному слову"
  },
  {
    value: "update_status",
    icon: "🟢",
    title: "Обновление статуса",
    description: "Кратко переключить статус аккаунта в онлайн"
  }
];

const DEFAULT_ACTIONS = ACTION_OPTIONS.map((option) => option.value);

function createInitialForm(): FormState {
  return {
    name: "",
    mode: "normal",
    account_sessions: [],
    enabled_actions: [...DEFAULT_ACTIONS],
    target_channels_input: ""
  };
}

function toForm(job: WarmupJob): FormState {
  return {
    name: job.name,
    mode: job.mode,
    account_sessions: [...job.account_sessions],
    enabled_actions: [...job.enabled_actions],
    target_channels_input: job.target_channels.join("\n")
  };
}

function parseTargetChannels(rawValue: string): string[] {
  const unique = new Set<string>();
  for (const line of rawValue.split("\n")) {
    const value = line.trim();
    if (!value) {
      continue;
    }
    unique.add(value);
  }
  return Array.from(unique);
}

function buildSessionOption(session: SessionInfo, account: AccountInfo | null): SessionOption {
  const firstName = account?.first_name?.trim() ?? "";
  const phone = account?.phone?.trim() || session.phone?.trim() || "";

  const label = firstName || phone || session.session_id;
  const description = phone ? `${session.session_id} · ${phone}` : session.session_id;

  return {
    session_id: session.session_id,
    label,
    description
  };
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

export default function WarmupPage() {
  const [userId, setUserId] = useState<string | null | undefined>(undefined);
  const [jobs, setJobs] = useState<WarmupJob[]>([]);
  const [sessions, setSessions] = useState<SessionOption[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [loadingSessions, setLoadingSessions] = useState<boolean>(false);

  const [error, setError] = useState<string | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);

  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingJob, setEditingJob] = useState<WarmupJob | null>(null);
  const [form, setForm] = useState<FormState>(createInitialForm());

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

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    setSessionsError(null);

    try {
      const response = await fetchJson<SessionsResponse>(`${API_BASE}/sessions`);
      const activeSessions = response.sessions.filter((session) => session.is_authorized);
      const settled = await Promise.allSettled(
        activeSessions.map(async (session): Promise<SessionOption> => {
          const info = await fetchJson<AccountInfoResponse>(
            `${API_BASE}/sessions/${session.session_id}/account/me`
          );
          return buildSessionOption(session, info.account);
        })
      );

      const options = activeSessions.map((session, index) => {
        const result = settled[index];
        if (result.status === "fulfilled") {
          return result.value;
        }
        return buildSessionOption(session, null);
      });

      setSessions(options.sort((a, b) => a.label.localeCompare(b.label)));

      if (settled.some((result) => result.status === "rejected")) {
        setSessionsError("Не удалось получить имя части аккаунтов. Показаны доступные данные сессий.");
      }
    } catch (e: unknown) {
      setSessions([]);
      if (e instanceof Error) {
        setSessionsError(e.message);
      } else {
        setSessionsError("Не удалось загрузить список активных сессий");
      }
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(STORAGE_USER_ID_KEY);
    setUserId(savedUserId);
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

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

  const openCreateModal = useCallback(() => {
    setEditingJob(null);
    setForm(createInitialForm());
    setModalError(null);
    setIsModalOpen(true);
  }, []);

  const openEditModal = useCallback((job: WarmupJob) => {
    setEditingJob(job);
    setForm(toForm(job));
    setModalError(null);
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingJob(null);
    setForm(createInitialForm());
    setModalError(null);
  }, [saving]);

  const toggleLocalActive = useCallback((jobId: string) => {
    setJobs((prev) =>
      prev.map((job) => (job.id === jobId ? { ...job, is_active: !job.is_active } : job))
    );
  }, []);

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

  const toggleAction = useCallback((actionValue: string) => {
    setForm((prev) => {
      const exists = prev.enabled_actions.includes(actionValue);
      const enabledActions = exists
        ? prev.enabled_actions.filter((item) => item !== actionValue)
        : [...prev.enabled_actions, actionValue];
      return {
        ...prev,
        enabled_actions: enabledActions
      };
    });
  }, []);

  const submitModal = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!userId) {
      setModalError("Пользователь не определен. Войдите заново.");
      return;
    }

    const trimmedName = form.name.trim();
    const targetChannels = parseTargetChannels(form.target_channels_input);

    if (!trimmedName) {
      setModalError("Введите название кампании");
      return;
    }
    if (form.account_sessions.length === 0) {
      setModalError("Выберите хотя бы один аккаунт");
      return;
    }
    if (form.enabled_actions.length === 0) {
      setModalError("Выберите хотя бы одно действие прогрева");
      return;
    }
    if (targetChannels.length === 0) {
      setModalError("Добавьте хотя бы один канал или чат для прогрева");
      return;
    }

    setSaving(true);
    setModalError(null);

    const payload: WarmupJobPayload = {
      name: trimmedName,
      mode: form.mode,
      account_sessions: form.account_sessions,
      enabled_actions: form.enabled_actions,
      target_channels: targetChannels
    };

    try {
      if (editingJob) {
        const updated = await fetchJson<WarmupJob>(
          `${API_BASE}/users/${userId}/warmup-jobs/${editingJob.id}`,
          {
            method: "PATCH",
            body: JSON.stringify(payload)
          }
        );
        setJobs((prev) => prev.map((job) => (job.id === updated.id ? updated : job)));
      } else {
        const created = await fetchJson<WarmupJob>(`${API_BASE}/users/${userId}/warmup-jobs`, {
          method: "POST",
          body: JSON.stringify(payload)
        });
        setJobs((prev) => [...prev, created]);
      }

      setIsModalOpen(false);
      setEditingJob(null);
      setForm(createInitialForm());
      setModalError(null);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setModalError(e.message);
      } else {
        setModalError("Не удалось сохранить кампанию");
      }
    } finally {
      setSaving(false);
    }
  }, [editingJob, form, userId]);

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Прогрев аккаунтов</h1>
        <button type="button" className={styles.createButton} onClick={openCreateModal}>
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

                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label="Редактировать кампанию"
                  onClick={() => openEditModal(job)}
                >
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

      {isModalOpen && (
        <div className={styles.modalOverlay} onClick={closeModal}>
          <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
            <h2 className={styles.modalTitle}>
              {editingJob ? "Редактирование кампании" : "Создание кампании"}
            </h2>
            {modalError && <p className={styles.modalError}>{modalError}</p>}

            <form className={styles.form} onSubmit={submitModal}>
              <div>
                <label className={styles.label} htmlFor="warmup-name">
                  Название кампании
                </label>
                <input
                  id="warmup-name"
                  className={styles.input}
                  value={form.name}
                  onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  required
                />
              </div>

              <div>
                <p className={styles.label}>Режим прогрева</p>
                <div className={styles.modeGrid}>
                  {MODE_OPTIONS.map((mode) => (
                    <label
                      key={mode.value}
                      className={`${styles.modeCard} ${styles[mode.colorClass]} ${
                        form.mode === mode.value ? styles.modeCardActive : ""
                      }`}
                    >
                      <input
                        type="radio"
                        name="warmup-mode"
                        className={styles.modeCardInput}
                        checked={form.mode === mode.value}
                        onChange={() => setForm((prev) => ({ ...prev, mode: mode.value }))}
                      />
                      <span className={styles.modeCardTitle}>{mode.label}</span>
                      <span className={styles.modeCardDescription}>{mode.description}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className={styles.label}>Аккаунты</p>
                {loadingSessions && <p className={styles.helperText}>Загрузка активных сессий...</p>}
                {!loadingSessions && sessionsError && <p className={styles.helperText}>{sessionsError}</p>}
                {!loadingSessions && sessions.length === 0 && (
                  <p className={styles.helperText}>Нет доступных активных сессий.</p>
                )}
                {!loadingSessions && sessions.length > 0 && (
                  <div className={styles.accountsGrid}>
                    {sessions.map((session) => (
                      <label key={session.session_id} className={styles.accountOption}>
                        <input
                          type="checkbox"
                          checked={form.account_sessions.includes(session.session_id)}
                          onChange={() => toggleAccountSession(session.session_id)}
                        />
                        <span className={styles.accountInfo}>
                          <span className={styles.accountLabel}>{session.label}</span>
                          <span className={styles.accountDescription}>{session.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <p className={styles.label}>Действия прогрева</p>
                <div className={styles.actionsGrid}>
                  {ACTION_OPTIONS.map((action) => (
                    <label key={action.value} className={styles.actionOption}>
                      <input
                        type="checkbox"
                        checked={form.enabled_actions.includes(action.value)}
                        onChange={() => toggleAction(action.value)}
                      />
                      <span className={styles.actionIcon} aria-hidden="true">
                        {action.icon}
                      </span>
                      <span className={styles.actionText}>
                        <span className={styles.actionTitle}>{action.title}</span>
                        <span className={styles.actionDescription}>{action.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className={styles.label} htmlFor="warmup-target-channels">
                  Каналы/чаты для прогрева
                </label>
                <textarea
                  id="warmup-target-channels"
                  className={styles.textarea}
                  value={form.target_channels_input}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, target_channels_input: event.target.value }))
                  }
                  rows={5}
                  placeholder={"@username\nhttps://t.me/channel_name"}
                />
                <p className={styles.helperText}>По одному @username или ссылке на строку.</p>
              </div>

              <div className={styles.modalActions}>
                <button
                  type="submit"
                  className={styles.createButton}
                  disabled={saving || loadingSessions}
                >
                  {saving ? "Сохранение..." : "Сохранить"}
                </button>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={closeModal}
                  disabled={saving}
                >
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
