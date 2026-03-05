"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./ai-commenting.module.css";

const API_BASE = "http://localhost:8000";
const STORAGE_USER_ID_KEY = "tg_client_user_id";
const SKELETON_ITEMS = 4;

interface AiCommentJob {
  id: string;
  user_id: string;
  name: string;
  account_sessions: string[];
  target_channels: string[];
  user_prompt: string;
  system_prompt: string;
  is_active: boolean;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

interface ApiErrorResponse {
  detail?: string;
  message?: string;
}

interface DeleteResponse {
  success: boolean;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    ...init,
    headers,
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

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.icon}>
      <path
        d="M4 20h4l10.5-10.5a1.41 1.41 0 0 0 0-2L16.5 5.5a1.41 1.41 0 0 0-2 0L4 16v4Z"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="m13.5 6.5 4 4"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.icon}>
      <path
        d="M5 7h14"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M10 11v6M14 11v6M8 7l1-2h6l1 2M7 7l1 12h8l1-12"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export default function AiCommentingPage() {
  const [userId, setUserId] = useState<string>("");
  const [userIdResolved, setUserIdResolved] = useState<boolean>(false);
  const [campaigns, setCampaigns] = useState<AiCommentJob[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [togglingJobId, setTogglingJobId] = useState<string | null>(null);

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(STORAGE_USER_ID_KEY);
    if (savedUserId) {
      setUserId(savedUserId);
    }
    setUserIdResolved(true);
  }, []);

  const loadCampaigns = useCallback(async (targetUserId: string) => {
    if (!targetUserId) {
      setCampaigns([]);
      setLoadError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setLoadError(null);

    try {
      const response = await fetchJson<AiCommentJob[]>(
        `${API_BASE}/users/${targetUserId}/ai-comment-jobs`
      );
      setCampaigns(response);
    } catch (error: unknown) {
      if (error instanceof Error) {
        setLoadError(error.message);
      } else {
        setLoadError("Не удалось загрузить кампании");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!userIdResolved) {
      return;
    }
    void loadCampaigns(userId);
  }, [loadCampaigns, userId, userIdResolved]);

  async function handleToggle(job: AiCommentJob) {
    if (!userId) {
      return;
    }

    setActionError(null);
    setNotice(null);
    setTogglingJobId(job.id);

    try {
      const updated = await fetchJson<AiCommentJob>(
        `${API_BASE}/users/${userId}/ai-comment-jobs/${job.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ is_active: !job.is_active })
        }
      );

      setCampaigns((currentCampaigns) =>
        currentCampaigns.map((campaign) => (campaign.id === job.id ? updated : campaign))
      );
    } catch (error: unknown) {
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Не удалось изменить статус кампании");
      }
    } finally {
      setTogglingJobId(null);
    }
  }

  async function handleDelete(job: AiCommentJob) {
    if (!userId) {
      return;
    }

    const confirmed = window.confirm(`Удалить кампанию «${job.name}»?`);
    if (!confirmed) {
      return;
    }

    setActionError(null);
    setNotice(null);
    setDeletingJobId(job.id);

    try {
      await fetchJson<DeleteResponse>(`${API_BASE}/users/${userId}/ai-comment-jobs/${job.id}`, {
        method: "DELETE"
      });

      setCampaigns((currentCampaigns) =>
        currentCampaigns.filter((campaign) => campaign.id !== job.id)
      );
    } catch (error: unknown) {
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Не удалось удалить кампанию");
      }
    } finally {
      setDeletingJobId(null);
    }
  }

  function handleCreate() {
    setActionError(null);
    setNotice("Форма создания кампании будет добавлена следующим шагом.");
  }

  function handleEdit(jobName: string) {
    setActionError(null);
    setNotice(`Редактирование кампании «${jobName}» будет добавлено следующим шагом.`);
  }

  const showEmptyState = !loading && !loadError && campaigns.length === 0;
  const showList = !loading && !loadError && campaigns.length > 0;

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Нейрокомментарии</h1>
          <p className={styles.subtitle}>Управляйте кампаниями AI-комментирования постов.</p>
        </div>
        <button type="button" className={styles.createButton} onClick={handleCreate}>
          + Создать кампанию
        </button>
      </div>

      {notice && <div className={styles.noticeBox}>{notice}</div>}
      {actionError && <div className={styles.errorBanner}>{actionError}</div>}

      {loading && (
        <div className={styles.skeletonList} aria-label="Загрузка кампаний">
          {Array.from({ length: SKELETON_ITEMS }, (_, index) => (
            <div key={index} className={styles.skeletonItem} />
          ))}
        </div>
      )}

      {loadError && (
        <div className={styles.errorState}>
          <p className={styles.stateTitle}>Не удалось загрузить кампании</p>
          <p className={styles.stateText}>{loadError}</p>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void loadCampaigns(userId)}
          >
            Повторить
          </button>
        </div>
      )}

      {showEmptyState && (
        <div className={styles.emptyState}>
          <p className={styles.stateTitle}>Нет кампаний. Создайте первую!</p>
          <p className={styles.stateText}>
            После создания здесь появится список активных и выключенных кампаний.
          </p>
        </div>
      )}

      {showList && (
        <div className={styles.list}>
          {campaigns.map((job) => {
            const isDeleting = deletingJobId === job.id;
            const isToggling = togglingJobId === job.id;

            return (
              <article key={job.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <div className={styles.rowName}>{job.name}</div>
                  <div className={styles.rowMeta}>
                    {job.account_sessions.length} аккаунт(а) · {job.target_channels.length} канал(а)
                  </div>
                </div>

                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.iconButton}
                    onClick={() => handleEdit(job.name)}
                    aria-label={`Редактировать кампанию ${job.name}`}
                    title="Редактировать кампанию"
                  >
                    <EditIcon />
                  </button>

                  <button
                    type="button"
                    className={styles.iconButtonDanger}
                    onClick={() => void handleDelete(job)}
                    disabled={isDeleting}
                    aria-label={`Удалить кампанию ${job.name}`}
                    title="Удалить кампанию"
                  >
                    <TrashIcon />
                  </button>

                  <label className={styles.toggleWrap}>
                    <input
                      type="checkbox"
                      className={styles.toggleInput}
                      checked={job.is_active}
                      disabled={isToggling}
                      onChange={() => void handleToggle(job)}
                    />
                    <span
                      className={`${styles.toggleSlider} ${
                        isToggling ? styles.toggleSliderLoading : ""
                      }`}
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
    </section>
  );
}
