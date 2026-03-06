"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type AccountInfo,
  type AiCommentJob,
  type AiCommentJobCreateRequest,
  type AiCommentJobHistoryStatus,
  type AiCommentJobPost,
  type AiCommentJobHistoryPostPreview,
  type ChatsResponse,
  createAiCommentJob,
  deleteAiCommentJob,
  getAiCommentJobHistory,
  getAiCommentJobHistoryPostPreview,
  getSessionAccount,
  listAiCommentJobs,
  listSessionChats,
  listSessions,
  updateAiCommentJob
} from "./api";
import styles from "./ai-commenting.module.css";

const STORAGE_USER_ID_KEY = "tg_client_user_id";
const CHATS_FETCH_LIMIT = 1000;
const SKELETON_ITEMS = 4;
const DEFAULT_SYSTEM_PROMPT = [
  "Ты пишешь краткий и естественный комментарий к посту в Telegram.",
  "Пиши по делу, без воды, без канцелярита и без упоминаний, что ты ИИ.",
  "Не придумывай факты, которых нет в посте.",
  "Верни только готовый текст комментария без кавычек, markdown и пояснений."
].join("\n");

interface SessionOption {
  session_id: string;
  label: string;
}

interface ChannelOption {
  value: string;
  label: string;
}

interface JobFormState {
  name: string;
  account_sessions: string[];
  target_channels: string[];
  user_prompt: string;
  system_prompt: string;
}

function createInitialForm(): JobFormState {
  return {
    name: "",
    account_sessions: [],
    target_channels: [],
    user_prompt: "",
    system_prompt: DEFAULT_SYSTEM_PROMPT
  };
}

function toForm(job: AiCommentJob): JobFormState {
  return {
    name: job.name,
    account_sessions: [...job.account_sessions],
    target_channels: [...job.target_channels],
    user_prompt: job.user_prompt,
    system_prompt: job.system_prompt
  };
}

function buildAccountLabel(
  account: AccountInfo | null,
  fallbackPhone: string | null,
  sessionId: string
): string {
  const firstName = account?.first_name?.trim();
  if (firstName) {
    return firstName;
  }

  const phone = account?.phone?.trim() || fallbackPhone?.trim();
  if (phone) {
    return phone;
  }

  return sessionId;
}

function mergeSessionOptions(options: SessionOption[], selectedSessionIds: string[]): SessionOption[] {
  const merged = new Map<string, SessionOption>();

  for (const option of options) {
    merged.set(option.session_id, option);
  }

  for (const sessionId of selectedSessionIds) {
    if (!merged.has(sessionId)) {
      merged.set(sessionId, {
        session_id: sessionId,
        label: `${sessionId} (неактивная сессия)`
      });
    }
  }

  return Array.from(merged.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function mergeChannelOptions(options: ChannelOption[], selectedChannels: string[]): ChannelOption[] {
  const merged = new Map<string, ChannelOption>();

  for (const option of options) {
    merged.set(option.value.toLowerCase(), option);
  }

  for (const channel of selectedChannels) {
    const normalized = channel.trim();
    if (!normalized) {
      continue;
    }

    const key = normalized.toLowerCase();
    if (!merged.has(key)) {
      merged.set(key, {
        value: normalized,
        label: `${normalized} (сохраненный канал)`
      });
    }
  }

  return Array.from(merged.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function formatHistoryTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function getHistoryStatusLabel(status: AiCommentJobHistoryStatus): string {
  switch (status) {
    case "posted":
      return "Опубликован";
    case "skipped":
      return "Пропущен";
    case "failed":
      return "Ошибка";
    default:
      return status;
  }
}

function getHistorySummary(item: AiCommentJobPost): string {
  switch (item.status) {
    case "posted":
      return item.comment_message_id
        ? `Комментарий опубликован, id комментария #${item.comment_message_id}.`
        : "Комментарий опубликован.";
    case "skipped":
      return "Пост пропущен и не требует новой публикации.";
    case "failed":
      return "Публикация не удалась.";
    default:
      return "";
  }
}

function getHistoryItemKey(item: AiCommentJobPost): string {
  return `${item.channel_id}-${item.message_id}-${item.created_at}`;
}

function getHistoryCommentText(item: AiCommentJobPost): string {
  const savedComment = item.comment_text?.trim();
  if (savedComment) {
    return savedComment;
  }

  switch (item.status) {
    case "posted":
      return "Для этой записи текст комментария еще не был сохранен.";
    case "skipped":
      return "Для этого поста комментарий не публиковался.";
    case "failed":
      return "Комментарий не был опубликован из-за ошибки.";
    default:
      return "Комментарий недоступен.";
  }
}

function getMediaTypeLabel(mediaType: string | null): string {
  switch (mediaType) {
    case "photo":
      return "фото";
    case "video":
      return "видео";
    case "audio":
      return "аудио";
    case "voice":
      return "голосовое";
    case "sticker":
      return "стикер";
    case "document":
      return "документ";
    default:
      return "медиа";
  }
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

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={styles.icon}>
      <path
        d="M12 8v5l3 2"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M3.5 12a8.5 8.5 0 1 0 2.49-6.01L3 9"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function SpinnerIcon() {
  return <span className={styles.actionSpinner} aria-hidden="true" />;
}

export default function AiCommentingPage() {
  const [userId, setUserId] = useState<string>("");
  const [userIdResolved, setUserIdResolved] = useState<boolean>(false);
  const [campaigns, setCampaigns] = useState<AiCommentJob[]>([]);
  const [sessions, setSessions] = useState<SessionOption[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [history, setHistory] = useState<AiCommentJobPost[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyJobId, setHistoryJobId] = useState<string | null>(null);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<AiCommentJobPost | null>(null);
  const [historyPreview, setHistoryPreview] = useState<AiCommentJobHistoryPostPreview | null>(null);
  const [historyPreviewLoading, setHistoryPreviewLoading] = useState<boolean>(false);
  const [historyPreviewError, setHistoryPreviewError] = useState<string | null>(null);

  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [togglingJobIds, setTogglingJobIds] = useState<Set<string>>(new Set());
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [historyLoadingJobId, setHistoryLoadingJobId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingJob, setEditingJob] = useState<AiCommentJob | null>(null);
  const [form, setForm] = useState<JobFormState>(createInitialForm);
  const [availableChannels, setAvailableChannels] = useState<ChannelOption[]>([]);
  const [loadingChannels, setLoadingChannels] = useState<boolean>(false);
  const [channelsError, setChannelsError] = useState<string | null>(null);
  const historyRequestIdRef = useRef<number>(0);
  const historyPreviewRequestIdRef = useRef<number>(0);

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
      const response = await listAiCommentJobs(targetUserId);
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

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError(null);

    try {
      const response = await listSessions();
      const authorizedSessions = response.sessions.filter((session) => session.is_authorized);

      const results = await Promise.allSettled(
        authorizedSessions.map(async (session): Promise<SessionOption> => {
          const info = await getSessionAccount(session.session_id);

          return {
            session_id: session.session_id,
            label: buildAccountLabel(info.account, session.phone, session.session_id)
          };
        })
      );

      const options = results
        .map((result, index) => {
          const session = authorizedSessions[index];
          if (result.status === "fulfilled") {
            return result.value;
          }

          return {
            session_id: session.session_id,
            label: buildAccountLabel(null, session.phone, session.session_id)
          };
        })
        .sort((left, right) => left.label.localeCompare(right.label));

      setSessions(options);
    } catch (error: unknown) {
      setSessions([]);
      if (error instanceof Error) {
        setSessionsError(error.message);
      } else {
        setSessionsError("Не удалось загрузить активные сессии");
      }
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!userIdResolved) {
      return;
    }
    void loadCampaigns(userId);
  }, [loadCampaigns, userId, userIdResolved]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!isModalOpen) {
      return;
    }

    if (form.account_sessions.length === 0) {
      setAvailableChannels([]);
      setChannelsError(null);
      setLoadingChannels(false);
      return;
    }

    let cancelled = false;

    async function loadChannelsForSelectedAccounts() {
      setLoadingChannels(true);
      setChannelsError(null);

      try {
        const settled = await Promise.allSettled(
          form.account_sessions.map((sessionId) => listSessionChats(sessionId, CHATS_FETCH_LIMIT))
        );

        if (cancelled) {
          return;
        }

        const successfulResponses = settled.filter(
          (entry): entry is PromiseFulfilledResult<ChatsResponse> => entry.status === "fulfilled"
        );

        if (successfulResponses.length === 0) {
          const firstError = settled.find(
            (entry): entry is PromiseRejectedResult => entry.status === "rejected"
          );
          throw new Error(
            firstError?.reason instanceof Error
              ? firstError.reason.message
              : "Не удалось загрузить каналы выбранных аккаунтов"
          );
        }

        const nextOptions = new Map<string, ChannelOption>();
        for (const response of successfulResponses) {
          for (const chat of response.value.chats) {
            if (chat.type !== "channel") {
              continue;
            }

            const value = chat.username ? `@${chat.username}` : String(chat.id);
            const normalizedValue = value.trim();
            if (!normalizedValue) {
              continue;
            }

            const key = normalizedValue.toLowerCase();
            if (nextOptions.has(key)) {
              continue;
            }

            const safeName = chat.name?.trim() ? chat.name.trim() : normalizedValue;
            const label = chat.username
              ? `${safeName} (${normalizedValue})`
              : `${safeName} (id: ${chat.id})`;

            nextOptions.set(key, {
              value: normalizedValue,
              label
            });
          }
        }

        setAvailableChannels(
          Array.from(nextOptions.values()).sort((left, right) => left.label.localeCompare(right.label))
        );

        if (successfulResponses.length !== form.account_sessions.length) {
          setChannelsError("Часть аккаунтов не удалось загрузить. Показаны доступные каналы.");
        }
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }

        setAvailableChannels([]);
        if (error instanceof Error) {
          setChannelsError(error.message);
        } else {
          setChannelsError("Не удалось загрузить каналы выбранных аккаунтов");
        }
      } finally {
        if (!cancelled) {
          setLoadingChannels(false);
        }
      }
    }

    void loadChannelsForSelectedAccounts();

    return () => {
      cancelled = true;
    };
  }, [form.account_sessions, isModalOpen]);

  function resetModalState() {
    setIsModalOpen(false);
    setEditingJob(null);
    setForm(createInitialForm());
    setAvailableChannels([]);
    setLoadingChannels(false);
    setChannelsError(null);
    setModalError(null);
  }

  function resetHistoryPreviewState() {
    historyPreviewRequestIdRef.current += 1;
    setSelectedHistoryItem(null);
    setHistoryPreview(null);
    setHistoryPreviewError(null);
    setHistoryPreviewLoading(false);
  }

  function resetHistoryState() {
    historyRequestIdRef.current += 1;
    resetHistoryPreviewState();
    setHistory([]);
    setHistoryError(null);
    setHistoryLoading(false);
    setHistoryLoadingJobId(null);
    setHistoryJobId(null);
  }

  function openCreateModal() {
    setActionError(null);
    setNotice(null);
    resetHistoryState();
    setEditingJob(null);
    setForm(createInitialForm());
    setAvailableChannels([]);
    setChannelsError(null);
    setModalError(null);
    setIsModalOpen(true);
  }

  function openEditModal(job: AiCommentJob) {
    setActionError(null);
    setNotice(null);
    resetHistoryState();
    setEditingJob(job);
    setForm(toForm(job));
    setAvailableChannels([]);
    setChannelsError(null);
    setModalError(null);
    setIsModalOpen(true);
  }

  function closeModal() {
    if (saving) {
      return;
    }

    resetModalState();
  }

  const loadHistory = useCallback(
    async (job: AiCommentJob) => {
      const requestId = historyRequestIdRef.current + 1;
      historyRequestIdRef.current = requestId;

      setActionError(null);
      setNotice(null);
      resetHistoryPreviewState();
      setHistory([]);
      setHistoryError(null);
      setHistoryLoading(true);
      setHistoryJobId(job.id);
      setHistoryLoadingJobId(job.id);

      if (!userId) {
        setHistoryError("Пользователь не определен. Войдите заново.");
        setHistoryLoading(false);
        setHistoryLoadingJobId(null);
        return;
      }

      try {
        const response = await getAiCommentJobHistory(userId, job.id);

        if (historyRequestIdRef.current !== requestId) {
          return;
        }

        setHistory(response);
      } catch (error: unknown) {
        if (historyRequestIdRef.current !== requestId) {
          return;
        }

        if (error instanceof Error) {
          setHistoryError(error.message);
        } else {
          setHistoryError("Не удалось загрузить историю кампании");
        }
      } finally {
        if (historyRequestIdRef.current === requestId) {
          setHistoryLoading(false);
          setHistoryLoadingJobId(null);
        }
      }
    },
    [userId]
  );

  const loadHistoryPreview = useCallback(
    async (job: AiCommentJob, item: AiCommentJobPost) => {
      const requestId = historyPreviewRequestIdRef.current + 1;
      historyPreviewRequestIdRef.current = requestId;

      setSelectedHistoryItem(item);
      setHistoryPreview(null);
      setHistoryPreviewError(null);
      setHistoryPreviewLoading(true);

      if (!userId) {
        setHistoryPreviewError("Пользователь не определен. Войдите заново.");
        setHistoryPreviewLoading(false);
        return;
      }

      try {
        const response = await getAiCommentJobHistoryPostPreview(
          userId,
          job.id,
          item.channel_id,
          item.message_id
        );

        if (historyPreviewRequestIdRef.current !== requestId) {
          return;
        }

        setHistoryPreview(response);
      } catch (error: unknown) {
        if (historyPreviewRequestIdRef.current !== requestId) {
          return;
        }

        if (error instanceof Error) {
          setHistoryPreviewError(error.message);
        } else {
          setHistoryPreviewError("Не удалось загрузить пост");
        }
      } finally {
        if (historyPreviewRequestIdRef.current === requestId) {
          setHistoryPreviewLoading(false);
        }
      }
    },
    [userId]
  );

  function closeHistory() {
    resetHistoryState();
  }

  async function submitModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!userId) {
      setModalError("Пользователь не определен. Войдите заново.");
      return;
    }

    const normalizedName = form.name.trim();
    const normalizedUserPrompt = form.user_prompt.trim();
    const normalizedSystemPrompt = form.system_prompt.trim();
    const normalizedSessions = Array.from(
      new Set(form.account_sessions.map((item) => item.trim()).filter(Boolean))
    );
    const normalizedChannels = Array.from(
      new Set(form.target_channels.map((item) => item.trim()).filter(Boolean))
    );

    if (!normalizedName) {
      setModalError("Введите название кампании");
      return;
    }
    if (normalizedSessions.length === 0) {
      setModalError("Выберите хотя бы один аккаунт");
      return;
    }
    if (normalizedChannels.length === 0) {
      setModalError("Выберите хотя бы один канал");
      return;
    }
    if (!normalizedUserPrompt) {
      setModalError("Введите пользовательский промпт");
      return;
    }
    if (!normalizedSystemPrompt) {
      setModalError("Введите системный промпт");
      return;
    }

    setSaving(true);
    setModalError(null);
    setActionError(null);
    setNotice(null);

    try {
      const payload: AiCommentJobCreateRequest = {
        name: normalizedName,
        account_sessions: normalizedSessions,
        target_channels: normalizedChannels,
        user_prompt: normalizedUserPrompt,
        system_prompt: normalizedSystemPrompt
      };

      if (editingJob) {
        const updated = await updateAiCommentJob(userId, editingJob.id, payload);

        setCampaigns((currentCampaigns) =>
          currentCampaigns.map((campaign) => (campaign.id === updated.id ? updated : campaign))
        );
        setNotice(`Кампания «${updated.name}» обновлена.`);
      } else {
        const created = await createAiCommentJob(userId, payload);

        setCampaigns((currentCampaigns) => [...currentCampaigns, created]);
        setNotice(`Кампания «${created.name}» создана.`);
      }

      resetModalState();
    } catch (error: unknown) {
      if (error instanceof Error) {
        setModalError(error.message);
      } else {
        setModalError("Не удалось сохранить кампанию");
      }
    } finally {
      setSaving(false);
    }
  }

  function toggleAccountSession(sessionId: string) {
    setForm((currentForm) => {
      const exists = currentForm.account_sessions.includes(sessionId);
      return {
        ...currentForm,
        account_sessions: exists
          ? currentForm.account_sessions.filter((currentSessionId) => currentSessionId !== sessionId)
          : [...currentForm.account_sessions, sessionId]
      };
    });
  }

  function toggleTargetChannel(channel: string) {
    setForm((currentForm) => {
      const exists = currentForm.target_channels.includes(channel);
      return {
        ...currentForm,
        target_channels: exists
          ? currentForm.target_channels.filter((currentChannel) => currentChannel !== channel)
          : [...currentForm.target_channels, channel]
      };
    });
  }

  async function handleToggle(job: AiCommentJob) {
    if (!userId) {
      setActionError("Пользователь не определен. Войдите заново.");
      return;
    }

    const nextValue = !job.is_active;
    setActionError(null);
    setNotice(null);
    setTogglingJobIds((currentIds) => {
      const nextIds = new Set(currentIds);
      nextIds.add(job.id);
      return nextIds;
    });
    setCampaigns((currentCampaigns) =>
      currentCampaigns.map((campaign) =>
        campaign.id === job.id ? { ...campaign, is_active: nextValue } : campaign
      )
    );

    try {
      const updated = await updateAiCommentJob(userId, job.id, { is_active: nextValue });

      setCampaigns((currentCampaigns) =>
        currentCampaigns.map((campaign) => (campaign.id === job.id ? updated : campaign))
      );
    } catch (error: unknown) {
      setCampaigns((currentCampaigns) =>
        currentCampaigns.map((campaign) =>
          campaign.id === job.id ? { ...campaign, is_active: job.is_active } : campaign
        )
      );
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Не удалось изменить статус кампании");
      }
    } finally {
      setTogglingJobIds((currentIds) => {
        const nextIds = new Set(currentIds);
        nextIds.delete(job.id);
        return nextIds;
      });
    }
  }

  async function handleDelete(job: AiCommentJob) {
    if (!userId) {
      setActionError("Пользователь не определен. Войдите заново.");
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
      await deleteAiCommentJob(userId, job.id);

      setCampaigns((currentCampaigns) =>
        currentCampaigns.filter((campaign) => campaign.id !== job.id)
      );
      if (historyJobId === job.id) {
        closeHistory();
      }
      setNotice(`Кампания «${job.name}» удалена.`);
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

  const showEmptyState = !loading && !loadError && campaigns.length === 0;
  const showList = !loading && !loadError && campaigns.length > 0;
  const displayedSessions = mergeSessionOptions(sessions, form.account_sessions);
  const displayedChannels = mergeChannelOptions(availableChannels, form.target_channels);
  const historyJob = historyJobId
    ? campaigns.find((campaign) => campaign.id === historyJobId) ?? null
    : null;
  const selectedHistoryItemKey = selectedHistoryItem ? getHistoryItemKey(selectedHistoryItem) : null;

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Нейрокомментарии</h1>
          <p className={styles.subtitle}>Управляйте кампаниями AI-комментирования постов.</p>
        </div>
        <button type="button" className={styles.createButton} onClick={openCreateModal}>
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
            const isToggling = togglingJobIds.has(job.id);
            const isHistoryLoading = historyLoadingJobId === job.id;

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
                    className={styles.historyButton}
                    onClick={() => void loadHistory(job)}
                    disabled={isDeleting || isHistoryLoading}
                    aria-busy={isHistoryLoading}
                    aria-label={`Открыть историю кампании ${job.name}`}
                    title={isHistoryLoading ? "Загрузка истории" : "История кампании"}
                  >
                    {isHistoryLoading ? <SpinnerIcon /> : <HistoryIcon />}
                    <span>История</span>
                  </button>

                  <button
                    type="button"
                    className={styles.iconButton}
                    onClick={() => openEditModal(job)}
                    disabled={isDeleting}
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
                    aria-busy={isDeleting}
                    aria-label={`Удалить кампанию ${job.name}`}
                    title={isDeleting ? "Удаление кампании" : "Удалить кампанию"}
                  >
                    {isDeleting ? <SpinnerIcon /> : <TrashIcon />}
                  </button>

                  <label className={styles.toggleWrap}>
                    <input
                      type="checkbox"
                      className={styles.toggleInput}
                      checked={job.is_active}
                      disabled={isToggling || isDeleting}
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

      {historyJob && (
        <div className={styles.historyOverlay}>
          <button
            type="button"
            className={styles.historyBackdrop}
            onClick={closeHistory}
            aria-label="Закрыть историю кампании"
          />

          <div
            className={styles.historyWorkspace}
            role="dialog"
            aria-modal="true"
            aria-labelledby="ai-comment-history-title"
          >
            <section className={styles.previewStage}>
              <div className={styles.previewPanel}>
                <div className={styles.previewHeader}>
                  <div>
                    <p className={styles.previewEyebrow}>Просмотр записи</p>
                    <h2 className={styles.previewTitle}>Пост и комментарий</h2>
                    <p className={styles.previewSubtitle}>
                      Выберите карточку в истории справа, чтобы подтянуть пост из Telegram в центр
                      экрана.
                    </p>
                  </div>
                  {selectedHistoryItem && (
                    <div className={styles.previewSelectionMeta}>
                      <span
                        className={`${styles.historyStatusBadge} ${
                          selectedHistoryItem.status === "posted"
                            ? styles.historyStatusPosted
                            : selectedHistoryItem.status === "failed"
                              ? styles.historyStatusFailed
                              : styles.historyStatusSkipped
                        }`}
                      >
                        {getHistoryStatusLabel(selectedHistoryItem.status)}
                      </span>
                      <p className={styles.previewSelectionText}>
                        {selectedHistoryItem.channel_id} · пост #{selectedHistoryItem.message_id}
                      </p>
                    </div>
                  )}
                </div>

                {!selectedHistoryItem && (
                  <div className={styles.emptyState}>
                    <p className={styles.stateTitle}>Ничего не выбрано</p>
                    <p className={styles.stateText}>
                      Справа остаётся список истории. Нажмите на нужную запись, и здесь откроются
                      исходный пост и сохранённый комментарий.
                    </p>
                  </div>
                )}

                {selectedHistoryItem && (
                  <div className={styles.previewGrid}>
                    <article className={styles.previewCard}>
                      <div className={styles.previewCardHeader}>
                        <div>
                          <p className={styles.previewCardEyebrow}>Пост</p>
                          <h3 className={styles.previewCardTitle}>
                            {historyPreview?.chat_name || selectedHistoryItem.channel_id}
                          </h3>
                        </div>
                        <p className={styles.previewCardMeta}>
                          {historyPreview?.post.date
                            ? formatHistoryTimestamp(historyPreview.post.date)
                            : formatHistoryTimestamp(selectedHistoryItem.created_at)}
                        </p>
                      </div>

                      {historyPreviewLoading && (
                        <div className={styles.previewLoadingBlock} aria-label="Загрузка поста">
                          <div className={styles.previewSkeletonLine} />
                          <div className={styles.previewSkeletonLine} />
                          <div className={styles.previewSkeletonLineShort} />
                        </div>
                      )}

                      {!historyPreviewLoading && historyPreviewError && (
                        <div className={styles.errorState}>
                          <p className={styles.stateTitle}>Не удалось загрузить пост</p>
                          <p className={styles.stateText}>{historyPreviewError}</p>
                          <button
                            type="button"
                            className={styles.secondaryButton}
                            onClick={() => void loadHistoryPreview(historyJob, selectedHistoryItem)}
                          >
                            Повторить
                          </button>
                        </div>
                      )}

                      {!historyPreviewLoading && !historyPreviewError && historyPreview && (
                        <>
                          <p className={styles.previewBody}>
                            {historyPreview.post.text.trim() || "У поста нет текстовой части."}
                          </p>
                          {historyPreview.post.has_media && (
                            <p className={styles.previewHint}>
                              В посте есть вложение: {getMediaTypeLabel(historyPreview.post.media_type)}
                              .
                            </p>
                          )}
                          <p className={styles.previewFootnote}>
                            Загружено через сессию {historyPreview.session_id}.
                          </p>
                        </>
                      )}
                    </article>

                    <article className={styles.previewCard}>
                      <div className={styles.previewCardHeader}>
                        <div>
                          <p className={styles.previewCardEyebrow}>Комментарий</p>
                          <h3 className={styles.previewCardTitle}>
                            {selectedHistoryItem.comment_message_id
                              ? `Комментарий #${selectedHistoryItem.comment_message_id}`
                              : "Сохраненный текст"}
                          </h3>
                        </div>
                        <p className={styles.previewCardMeta}>
                          {formatHistoryTimestamp(selectedHistoryItem.created_at)}
                        </p>
                      </div>

                      <p className={styles.previewBody}>{getHistoryCommentText(selectedHistoryItem)}</p>
                      <p className={styles.previewHint}>{getHistorySummary(selectedHistoryItem)}</p>
                      {selectedHistoryItem.error && (
                        <p className={styles.previewErrorNote}>{selectedHistoryItem.error}</p>
                      )}
                    </article>
                  </div>
                )}
              </div>
            </section>

            <aside className={styles.drawer}>
              <div className={styles.drawerHeader}>
                <div>
                  <p className={styles.drawerEyebrow}>История кампании</p>
                  <h2 id="ai-comment-history-title" className={styles.drawerTitle}>
                    {historyJob.name}
                  </h2>
                  <p className={styles.drawerSubtitle}>
                    Последние статусы по постам, комментариям и ошибкам этой кампании.
                  </p>
                </div>
                <button type="button" className={styles.secondaryButton} onClick={closeHistory}>
                  Закрыть
                </button>
              </div>

              {historyLoading && (
                <div className={styles.historyLoadingState} aria-label="Загрузка истории кампании">
                  {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className={styles.historySkeletonItem} />
                  ))}
                </div>
              )}

              {!historyLoading && historyError && (
                <div className={styles.errorState}>
                  <p className={styles.stateTitle}>Не удалось загрузить историю</p>
                  <p className={styles.stateText}>{historyError}</p>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void loadHistory(historyJob)}
                  >
                    Повторить
                  </button>
                </div>
              )}

              {!historyLoading && !historyError && history.length === 0 && (
                <div className={styles.emptyState}>
                  <p className={styles.stateTitle}>История пока пуста</p>
                  <p className={styles.stateText}>
                    Как только кампания обработает новые посты, здесь появятся статусы публикаций.
                  </p>
                </div>
              )}

              {!historyLoading && !historyError && history.length > 0 && (
                <div className={styles.historyList}>
                  {history.map((item) => {
                    const itemKey = getHistoryItemKey(item);
                    const isSelected = itemKey === selectedHistoryItemKey;

                    return (
                      <button
                        key={itemKey}
                        type="button"
                        className={`${styles.historyItem} ${
                          isSelected ? styles.historyItemActive : ""
                        }`}
                        onClick={() => void loadHistoryPreview(historyJob, item)}
                        aria-pressed={isSelected}
                      >
                        <div className={styles.historyTopRow}>
                          <span
                            className={`${styles.historyStatusBadge} ${
                              item.status === "posted"
                                ? styles.historyStatusPosted
                                : item.status === "failed"
                                  ? styles.historyStatusFailed
                                  : styles.historyStatusSkipped
                            }`}
                          >
                            {getHistoryStatusLabel(item.status)}
                          </span>
                          <time className={styles.historyDate} dateTime={item.created_at}>
                            {formatHistoryTimestamp(item.created_at)}
                          </time>
                        </div>

                        <p className={styles.historyChannel}>{item.channel_id}</p>
                        <p className={styles.historyMeta}>
                          Пост #{item.message_id}
                          {item.comment_message_id ? ` · комментарий #${item.comment_message_id}` : ""}
                        </p>
                        <p className={styles.historySummary}>{getHistorySummary(item)}</p>
                        {item.error && <p className={styles.historyErrorText}>{item.error}</p>}
                      </button>
                    );
                  })}
                </div>
              )}
            </aside>
          </div>
        </div>
      )}

      {isModalOpen && (
        <div className={styles.modalOverlay} onClick={closeModal}>
          <div className={styles.modal} onClick={(event) => event.stopPropagation()}>
            <h2 className={styles.modalTitle}>
              {editingJob ? "Редактировать кампанию" : "Создать кампанию"}
            </h2>

            {modalError && <div className={styles.errorBanner}>{modalError}</div>}

            <form className={styles.form} onSubmit={submitModal}>
              <div>
                <label className={styles.label} htmlFor="campaign-name">
                  Название кампании
                </label>
                <input
                  id="campaign-name"
                  className={styles.input}
                  value={form.name}
                  onChange={(event) =>
                    setForm((currentForm) => ({ ...currentForm, name: event.target.value }))
                  }
                  maxLength={120}
                  required
                />
              </div>

              <div>
                <p className={styles.label}>Аккаунты</p>
                <p className={styles.helperText}>Выбрано: {form.account_sessions.length}</p>
                {sessionsLoading && <p className={styles.helperText}>Загрузка активных сессий...</p>}
                {!sessionsLoading && sessionsError && (
                  <div className={styles.inlineState}>
                    <p className={styles.helperText}>{sessionsError}</p>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => void loadSessions()}
                    >
                      Повторить
                    </button>
                  </div>
                )}
                {!sessionsLoading && !sessionsError && displayedSessions.length === 0 && (
                  <p className={styles.helperText}>Нет активных сессий.</p>
                )}
                {!sessionsLoading && displayedSessions.length > 0 && (
                  <div className={styles.gridOptions}>
                    {displayedSessions.map((session) => (
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
                )}
              </div>

              <div>
                <p className={styles.label}>Каналы</p>
                <p className={styles.helperText}>Выбрано: {form.target_channels.length}</p>
                {loadingChannels && <p className={styles.helperText}>Загрузка каналов...</p>}
                {!loadingChannels && channelsError && <p className={styles.helperText}>{channelsError}</p>}
                {!loadingChannels && form.account_sessions.length === 0 && (
                  <p className={styles.helperText}>Сначала выберите хотя бы один аккаунт.</p>
                )}
                {!loadingChannels &&
                  form.account_sessions.length > 0 &&
                  !channelsError &&
                  displayedChannels.length === 0 && (
                    <p className={styles.helperText}>Нет доступных каналов для выбранных аккаунтов.</p>
                  )}
                {!loadingChannels && displayedChannels.length > 0 && (
                  <div className={styles.gridOptions}>
                    {displayedChannels.map((channel) => (
                      <label key={channel.value} className={styles.checkboxLabel}>
                        <input
                          type="checkbox"
                          checked={form.target_channels.includes(channel.value)}
                          onChange={() => toggleTargetChannel(channel.value)}
                        />
                        <span>{channel.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label className={styles.label} htmlFor="user-prompt">
                  Пользовательский промпт
                </label>
                <textarea
                  id="user-prompt"
                  className={styles.textarea}
                  value={form.user_prompt}
                  onChange={(event) =>
                    setForm((currentForm) => ({
                      ...currentForm,
                      user_prompt: event.target.value
                    }))
                  }
                  rows={5}
                  required
                />
              </div>

              <div>
                <label className={styles.label} htmlFor="system-prompt">
                  Системный промпт
                </label>
                <textarea
                  id="system-prompt"
                  className={styles.textarea}
                  value={form.system_prompt}
                  onChange={(event) =>
                    setForm((currentForm) => ({
                      ...currentForm,
                      system_prompt: event.target.value
                    }))
                  }
                  rows={6}
                  required
                />
              </div>

              <div className={styles.modalActions}>
                <button
                  type="submit"
                  className={styles.createButton}
                  disabled={saving || sessionsLoading || loadingChannels}
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
