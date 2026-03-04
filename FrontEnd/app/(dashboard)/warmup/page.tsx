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

interface WarmupJobsResponse extends Array<WarmupJob> {}

interface WarmupJobDeleteResponse {
  success: boolean;
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
  first_name?: string | null;
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

interface ApiErrorResponse {
  detail?: string;
  message?: string;
}

interface SessionOption {
  session_id: string;
  first_name: string;
  phone: string;
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
  icon: string;
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
    icon: "🛡️",
    description: "5–15 действий/день, длинные паузы",
    colorClass: "modeCardCautious"
  },
  {
    value: "normal",
    label: "Нормальный",
    icon: "⚖️",
    description: "20–50 действий/день, умеренные паузы",
    colorClass: "modeCardNormal"
  },
  {
    value: "aggressive",
    label: "Агрессивный",
    icon: "🔥",
    description: "60–120 действий/день, короткие паузы",
    colorClass: "modeCardAggressive"
  }
];

const ACTION_OPTIONS: ActionOption[] = [
  {
    value: "read_messages",
    icon: "📖",
    title: "Чтение сообщений",
    description: "Читает последние сообщения в чате"
  },
  {
    value: "react_to_message",
    icon: "💬",
    title: "Реакция на сообщение",
    description: "Ставит одну нейтральную реакцию"
  },
  {
    value: "join_channel",
    icon: "➕",
    title: "Подписка на канал",
    description: "Подписывается на канал из списка"
  },
  {
    value: "view_story",
    icon: "👀",
    title: "Просмотр историй",
    description: "Открывает несколько историй"
  },
  {
    value: "search_global",
    icon: "🔎",
    title: "Глобальный поиск",
    description: "Делает случайный поисковый запрос"
  },
  {
    value: "update_status",
    icon: "🟢",
    title: "Обновление статуса",
    description: "Коротко включает статус «в сети»"
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
  for (const line of rawValue.split(/\r?\n/)) {
    const value = line.trim();
    if (!value) {
      continue;
    }
    unique.add(value);
  }
  return Array.from(unique);
}

function buildSessionOption(session: SessionInfo, account: AccountInfo | null): SessionOption {
  const firstName = (account?.first_name ?? session.first_name ?? "").trim();
  const phone = (account?.phone ?? session.phone ?? "").trim();

  const label = firstName || phone || session.session_id;
  const descriptionParts = [firstName, phone].filter(Boolean);
  const description = descriptionParts.length > 0 ? descriptionParts.join(" · ") : session.session_id;

  return {
    session_id: session.session_id,
    first_name: firstName,
    phone,
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
    const errorBody = (await response.json().catch(() => null)) as ApiErrorResponse | null;
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
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [togglingJobIds, setTogglingJobIds] = useState<Set<string>>(() => new Set());

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
      const response = await fetchJson<WarmupJobsResponse>(
        `${API_BASE}/users/${targetUserId}/warmup-jobs`
      );
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
  const availableSessionIds = useMemo(() => new Set(sessions.map((session) => session.session_id)), [sessions]);
  const missingSelectedSessionIds = useMemo(
    () =>
      form.account_sessions.filter((sessionId) => !availableSessionIds.has(sessionId)).sort((a, b) =>
        a.localeCompare(b)
      ),
    [availableSessionIds, form.account_sessions]
  );

  const openCreateModal = useCallback(() => {
    setEditingJob(null);
    setForm(createInitialForm());
    setModalError(null);
    void loadSessions();
    setIsModalOpen(true);
  }, [loadSessions]);

  const openEditModal = useCallback((job: WarmupJob) => {
    setEditingJob(job);
    setForm(toForm(job));
    setModalError(null);
    void loadSessions();
    setIsModalOpen(true);
  }, [loadSessions]);

  const closeModal = useCallback(() => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingJob(null);
    setForm(createInitialForm());
    setModalError(null);
  }, [saving]);

  const toggleJobActive = useCallback(async (job: WarmupJob) => {
    if (!userId) {
      setError("Пользователь не определен. Войдите заново.");
      return;
    }

    const nextValue = !job.is_active;
    setTogglingJobIds((prev) => {
      const next = new Set(prev);
      next.add(job.id);
      return next;
    });
    setError(null);
    setJobs((prev) => prev.map((item) => (item.id === job.id ? { ...item, is_active: nextValue } : item)));

    try {
      const updated = await fetchJson<WarmupJob>(
        `${API_BASE}/users/${userId}/warmup-jobs/${job.id}`,
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
        setError("Не удалось изменить статус кампании прогрева");
      }
    } finally {
      setTogglingJobIds((prev) => {
        const next = new Set(prev);
        next.delete(job.id);
        return next;
      });
    }
  }, [userId]);

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

  const removeJob = useCallback(async (job: WarmupJob) => {
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
      await fetchJson<WarmupJobDeleteResponse>(
        `${API_BASE}/users/${userId}/warmup-jobs/${job.id}`,
        {
          method: "DELETE"
        }
      );
      setJobs((prev) => prev.filter((item) => item.id !== job.id));
    } catch (e: unknown) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Не удалось удалить кампанию прогрева");
      }
    } finally {
      setDeletingJobId(null);
    }
  }, [userId]);

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
          {sortedJobs.map((job) => {
            const isToggling = togglingJobIds.has(job.id);
            const isDeleting = deletingJobId === job.id;

            return (
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
                    disabled={isDeleting}
                  >
                    ✏️
                  </button>

                  <button
                    type="button"
                    className={styles.iconButtonDanger}
                    aria-label="Удалить кампанию"
                    onClick={() => void removeJob(job)}
                    disabled={isDeleting}
                  >
                    {isDeleting ? "..." : "🗑️"}
                  </button>

                  <label className={styles.toggleWrap}>
                    <input
                      type="checkbox"
                      className={styles.toggleInput}
                      checked={job.is_active}
                      onChange={() => void toggleJobActive(job)}
                      disabled={isToggling || isDeleting}
                    />
                    <span
                      className={`${styles.toggleSlider} ${isToggling ? styles.toggleSliderLoading : ""}`}
                      aria-hidden="true"
                    >
                      {isToggling && <span className={styles.toggleSpinner} />}
                    </span>
                    <span className={styles.toggleLabel}>{job.is_active ? "Вкл" : "Выкл"}</span>
                  </label>
                </div>
              </article>
            );
          })}
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
                      <span className={styles.modeCardHeader}>
                        <span className={styles.modeCardIcon} aria-hidden="true">
                          {mode.icon}
                        </span>
                        <span className={styles.modeCardTitle}>{mode.label}</span>
                      </span>
                      <span className={styles.modeCardDescription}>{mode.description}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className={styles.label}>Аккаунты</p>
                <p className={styles.helperText}>Выбрано: {form.account_sessions.length}</p>
                {loadingSessions && <p className={styles.helperText}>Загрузка активных сессий...</p>}
                {!loadingSessions && sessionsError && <p className={styles.helperText}>{sessionsError}</p>}
                {!loadingSessions && missingSelectedSessionIds.length > 0 && (
                  <>
                    <p className={styles.helperText}>
                      Часть выбранных сессий сейчас недоступна в списке активных:
                    </p>
                    <div className={styles.missingAccountsList}>
                      {missingSelectedSessionIds.map((sessionId) => (
                        <button
                          key={sessionId}
                          type="button"
                          className={styles.missingAccountChip}
                          onClick={() => toggleAccountSession(sessionId)}
                        >
                          {sessionId} · убрать
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {!loadingSessions && sessions.length === 0 && (
                  <p className={styles.helperText}>Нет доступных активных сессий.</p>
                )}
                {!loadingSessions && sessions.length > 0 && (
                  <div className={styles.accountsGrid}>
                    {sessions.map((session) => (
                      <label
                        key={session.session_id}
                        className={`${styles.accountOption} ${
                          form.account_sessions.includes(session.session_id)
                            ? styles.accountOptionActive
                            : ""
                        }`}
                      >
                        <input
                          type="checkbox"
                          className={styles.accountCheckbox}
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
                    <label
                      key={action.value}
                      className={`${styles.actionOption} ${
                        form.enabled_actions.includes(action.value) ? styles.actionOptionActive : ""
                      }`}
                    >
                      <span className={styles.actionIconWrap} aria-hidden="true">
                        <span className={styles.actionIcon}>{action.icon}</span>
                      </span>
                      <span className={styles.actionText}>
                        <span className={styles.actionTitle}>{action.title}</span>
                        <span className={styles.actionDescription}>{action.description}</span>
                      </span>
                      <input
                        type="checkbox"
                        className={styles.actionCheckbox}
                        checked={form.enabled_actions.includes(action.value)}
                        onChange={() => toggleAction(action.value)}
                      />
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
