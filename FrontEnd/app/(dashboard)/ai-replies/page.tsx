"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type AccountInfo,
  type AiReplyJob,
  type AiReplyJobCreateRequest,
  type AiReplyJobHistoryStatus,
  type AiReplyJobMessage,
  type ChatsResponse,
  createAiReplyJob,
  deleteAiReplyJob,
  getAiReplyJobHistory,
  getSessionAccount,
  listAiReplyJobs,
  listSessionChats,
  listSessions,
  updateAiReplyJob
} from "./api";
import styles from "../ai-commenting/ai-commenting.module.css";

const STORAGE_USER_ID_KEY = "tg_client_user_id";
const CHATS_FETCH_LIMIT = 1000;
const SKELETON_ITEMS = 4;
const DEFAULT_REPLY_PROMPT = [
  "Отвечай по делу, спокойно и естественно.",
  "Если пользователь задал вопрос, дай прямой ответ без воды.",
  "Не упоминай, что ты ИИ, и не добавляй лишние дисклеймеры."
].join("\n");

interface SessionOption {
  session_id: string;
  label: string;
}

interface ChatOption {
  value: string;
  label: string;
}

interface JobFormState {
  name: string;
  account_sessions: string[];
  target_chats: string[];
  triggers_input: string;
  reply_prompt: string;
}

function createInitialForm(): JobFormState {
  return {
    name: "",
    account_sessions: [],
    target_chats: [],
    triggers_input: "",
    reply_prompt: DEFAULT_REPLY_PROMPT
  };
}

function parseMultilineValues(value: string): string[] {
  const unique = new Set<string>();
  for (const line of value.split(/\r?\n/)) {
    const normalized = line.trim();
    if (!normalized) {
      continue;
    }
    unique.add(normalized);
  }
  return Array.from(unique);
}

function toForm(job: AiReplyJob): JobFormState {
  return {
    name: job.name,
    account_sessions: [...job.account_sessions],
    target_chats: [...job.target_chats],
    triggers_input: job.triggers.join("\n"),
    reply_prompt: job.reply_prompt
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

function mergeChatOptions(options: ChatOption[], selectedChats: string[]): ChatOption[] {
  const merged = new Map<string, ChatOption>();

  for (const option of options) {
    merged.set(option.value.toLowerCase(), option);
  }

  for (const chat of selectedChats) {
    const normalized = chat.trim();
    if (!normalized) {
      continue;
    }

    const key = normalized.toLowerCase();
    if (!merged.has(key)) {
      merged.set(key, {
        value: normalized,
        label: `${normalized} (сохраненный чат)`
      });
    }
  }

  return Array.from(merged.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function formatHistoryTimestamp(value: string | null): string {
  if (!value) {
    return "Нет времени";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function getHistoryStatusLabel(status: AiReplyJobHistoryStatus): string {
  switch (status) {
    case "replied":
      return "Ответ отправлен";
    case "skipped":
      return "Пропущено";
    case "failed":
      return "Ошибка";
    default:
      return status;
  }
}

function getHistorySummary(item: AiReplyJobMessage): string {
  switch (item.status) {
    case "replied":
      return item.reply_message_id
        ? `Ответ отправлен, id сообщения #${item.reply_message_id}.`
        : "Ответ отправлен.";
    case "skipped":
      return item.error?.trim() || "Сообщение не попало под триггеры.";
    case "failed":
      return "Ответ не был отправлен.";
    default:
      return "";
  }
}

function getHistoryItemKey(item: AiReplyJobMessage): string {
  return `${item.chat_id}-${item.message_id}-${item.created_at}`;
}

function getMessageText(item: AiReplyJobMessage): string {
  const text = item.message_text?.trim();
  return text || "У сообщения нет текстовой части.";
}

function getReplyText(item: AiReplyJobMessage): string {
  const text = item.reply_text?.trim();
  if (text) {
    return text;
  }

  switch (item.status) {
    case "replied":
      return "Текст ответа не был сохранен.";
    case "skipped":
      return "Ответ не отправлялся.";
    case "failed":
      return "Ответ не был отправлен из-за ошибки.";
    default:
      return "Ответ недоступен.";
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

export default function AiRepliesPage() {
  const [userId, setUserId] = useState<string>("");
  const [userIdResolved, setUserIdResolved] = useState<boolean>(false);
  const [campaigns, setCampaigns] = useState<AiReplyJob[]>([]);
  const [sessions, setSessions] = useState<SessionOption[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);

  const [history, setHistory] = useState<AiReplyJobMessage[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyJobId, setHistoryJobId] = useState<string | null>(null);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<AiReplyJobMessage | null>(null);

  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [togglingJobIds, setTogglingJobIds] = useState<Set<string>>(new Set());
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [historyLoadingJobId, setHistoryLoadingJobId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingJob, setEditingJob] = useState<AiReplyJob | null>(null);
  const [form, setForm] = useState<JobFormState>(createInitialForm);
  const [availableChats, setAvailableChats] = useState<ChatOption[]>([]);
  const [loadingChats, setLoadingChats] = useState<boolean>(false);
  const [chatsError, setChatsError] = useState<string | null>(null);
  const historyRequestIdRef = useRef<number>(0);

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
      const response = await listAiReplyJobs(targetUserId);
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
      setAvailableChats([]);
      setChatsError(null);
      setLoadingChats(false);
      return;
    }

    let cancelled = false;

    async function loadChatsForSelectedAccounts() {
      setLoadingChats(true);
      setChatsError(null);

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
              : "Не удалось загрузить чаты выбранных аккаунтов"
          );
        }

        const nextOptions = new Map<string, ChatOption>();
        for (const response of successfulResponses) {
          for (const chat of response.value.chats) {
            if (chat.type === "channel") {
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

        setAvailableChats(
          Array.from(nextOptions.values()).sort((left, right) => left.label.localeCompare(right.label))
        );

        if (successfulResponses.length !== form.account_sessions.length) {
          setChatsError("Часть аккаунтов не удалось загрузить. Показаны доступные чаты.");
        }
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }

        setAvailableChats([]);
        if (error instanceof Error) {
          setChatsError(error.message);
        } else {
          setChatsError("Не удалось загрузить чаты выбранных аккаунтов");
        }
      } finally {
        if (!cancelled) {
          setLoadingChats(false);
        }
      }
    }

    void loadChatsForSelectedAccounts();

    return () => {
      cancelled = true;
    };
  }, [form.account_sessions, isModalOpen]);

  function resetModalState() {
    setIsModalOpen(false);
    setEditingJob(null);
    setForm(createInitialForm());
    setAvailableChats([]);
    setLoadingChats(false);
    setChatsError(null);
    setModalError(null);
  }

  function resetHistoryState() {
    historyRequestIdRef.current += 1;
    setHistory([]);
    setHistoryError(null);
    setHistoryLoading(false);
    setHistoryLoadingJobId(null);
    setHistoryJobId(null);
    setSelectedHistoryItem(null);
  }

  function openCreateModal() {
    setActionError(null);
    setNotice(null);
    resetHistoryState();
    setEditingJob(null);
    setForm(createInitialForm());
    setAvailableChats([]);
    setChatsError(null);
    setModalError(null);
    setIsModalOpen(true);
  }

  function openEditModal(job: AiReplyJob) {
    setActionError(null);
    setNotice(null);
    resetHistoryState();
    setEditingJob(job);
    setForm(toForm(job));
    setAvailableChats([]);
    setChatsError(null);
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
    async (job: AiReplyJob) => {
      const requestId = historyRequestIdRef.current + 1;
      historyRequestIdRef.current = requestId;

      setActionError(null);
      setNotice(null);
      setHistory([]);
      setHistoryError(null);
      setHistoryLoading(true);
      setHistoryJobId(job.id);
      setHistoryLoadingJobId(job.id);
      setSelectedHistoryItem(null);

      if (!userId) {
        setHistoryError("Пользователь не определен. Войдите заново.");
        setHistoryLoading(false);
        setHistoryLoadingJobId(null);
        return;
      }

      try {
        const response = await getAiReplyJobHistory(userId, job.id);

        if (historyRequestIdRef.current !== requestId) {
          return;
        }

        setHistory(response);
        setSelectedHistoryItem(response[0] ?? null);
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
    const normalizedSessions = Array.from(
      new Set(form.account_sessions.map((item) => item.trim()).filter(Boolean))
    );
    const normalizedChats = Array.from(
      new Set(form.target_chats.map((item) => item.trim()).filter(Boolean))
    );
    const normalizedTriggers = parseMultilineValues(form.triggers_input);
    const normalizedReplyPrompt = form.reply_prompt.trim();

    if (!normalizedName) {
      setModalError("Введите название кампании");
      return;
    }
    if (normalizedSessions.length === 0) {
      setModalError("Выберите хотя бы один аккаунт");
      return;
    }
    if (normalizedChats.length === 0) {
      setModalError("Выберите хотя бы один чат");
      return;
    }
    if (normalizedTriggers.length === 0) {
      setModalError("Добавьте хотя бы один триггер");
      return;
    }
    if (!normalizedReplyPrompt) {
      setModalError("Введите промпт ответа");
      return;
    }

    setSaving(true);
    setModalError(null);
    setActionError(null);
    setNotice(null);

    try {
      const payload: AiReplyJobCreateRequest = {
        name: normalizedName,
        account_sessions: normalizedSessions,
        target_chats: normalizedChats,
        triggers: normalizedTriggers,
        reply_prompt: normalizedReplyPrompt
      };

      if (editingJob) {
        const updated = await updateAiReplyJob(userId, editingJob.id, payload);
        setCampaigns((currentCampaigns) =>
          currentCampaigns.map((campaign) => (campaign.id === updated.id ? updated : campaign))
        );
        setNotice(`Кампания «${updated.name}» обновлена.`);
      } else {
        const created = await createAiReplyJob(userId, payload);
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

  function toggleTargetChat(chat: string) {
    setForm((currentForm) => {
      const exists = currentForm.target_chats.includes(chat);
      return {
        ...currentForm,
        target_chats: exists
          ? currentForm.target_chats.filter((currentChat) => currentChat !== chat)
          : [...currentForm.target_chats, chat]
      };
    });
  }

  async function handleToggle(job: AiReplyJob) {
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
      const updated = await updateAiReplyJob(userId, job.id, { is_active: nextValue });
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

  async function handleDelete(job: AiReplyJob) {
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
      await deleteAiReplyJob(userId, job.id);
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
  const displayedChats = mergeChatOptions(availableChats, form.target_chats);
  const selectedHistoryItemKey = selectedHistoryItem ? getHistoryItemKey(selectedHistoryItem) : null;
  const historyJob = historyJobId
    ? campaigns.find((campaign) => campaign.id === historyJobId) ?? null
    : null;

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Нейроответы</h1>
          <p className={styles.subtitle}>
            Кампании AI-ответов на входящие сообщения в чатах по заданным триггерам.
          </p>
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
            После создания здесь появятся кампании с триггерами, чатами и историей ответов.
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
                    {job.account_sessions.length} аккаунт(а) · {job.target_chats.length} чат(а) ·{" "}
                    {job.triggers.length} триггер(ов)
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
            aria-labelledby="ai-reply-history-title"
          >
            <section className={styles.previewStage}>
              <div className={styles.previewPanel}>
                <div className={styles.previewHeader}>
                  <div>
                    <p className={styles.previewEyebrow}>Просмотр записи</p>
                    <h2 className={styles.previewTitle}>Сообщение и ответ</h2>
                    <p className={styles.previewSubtitle}>
                      Выберите запись справа, чтобы посмотреть входящее сообщение, совпавший
                      триггер и финальный ответ.
                    </p>
                  </div>
                  {selectedHistoryItem && (
                    <div className={styles.previewSelectionMeta}>
                      <span
                        className={`${styles.historyStatusBadge} ${
                          selectedHistoryItem.status === "replied"
                            ? styles.historyStatusPosted
                            : selectedHistoryItem.status === "failed"
                              ? styles.historyStatusFailed
                              : styles.historyStatusSkipped
                        }`}
                      >
                        {getHistoryStatusLabel(selectedHistoryItem.status)}
                      </span>
                      <p className={styles.previewSelectionText}>
                        {selectedHistoryItem.chat_name || selectedHistoryItem.chat_id} · сообщение #
                        {selectedHistoryItem.message_id}
                      </p>
                    </div>
                  )}
                </div>

                {!selectedHistoryItem && (
                  <div className={styles.emptyState}>
                    <p className={styles.stateTitle}>Ничего не выбрано</p>
                    <p className={styles.stateText}>
                      Справа остаётся список истории. Выберите карточку, чтобы посмотреть входящее
                      сообщение и сформированный ответ.
                    </p>
                  </div>
                )}

                {selectedHistoryItem && (
                  <div className={styles.previewGrid}>
                    <article className={styles.previewCard}>
                      <div className={styles.previewCardHeader}>
                        <div>
                          <p className={styles.previewCardEyebrow}>Входящее сообщение</p>
                          <h3 className={styles.previewCardTitle}>
                            {selectedHistoryItem.chat_name || selectedHistoryItem.chat_id}
                          </h3>
                        </div>
                        <p className={styles.previewCardMeta}>
                          {formatHistoryTimestamp(
                            selectedHistoryItem.message_date || selectedHistoryItem.created_at
                          )}
                        </p>
                      </div>

                      <p className={styles.previewBody}>{getMessageText(selectedHistoryItem)}</p>
                      <p className={styles.previewHint}>
                        {selectedHistoryItem.sender_id
                          ? `Sender id: ${selectedHistoryItem.sender_id}.`
                          : "Sender id не сохранен."}
                      </p>
                      <p className={styles.previewFootnote}>
                        {selectedHistoryItem.matched_trigger
                          ? `Совпавший триггер: ${selectedHistoryItem.matched_trigger}`
                          : "Совпавший триггер не определен."}
                      </p>
                    </article>

                    <article className={styles.previewCard}>
                      <div className={styles.previewCardHeader}>
                        <div>
                          <p className={styles.previewCardEyebrow}>Ответ</p>
                          <h3 className={styles.previewCardTitle}>
                            {selectedHistoryItem.reply_message_id
                              ? `Ответ #${selectedHistoryItem.reply_message_id}`
                              : "Сохраненный результат"}
                          </h3>
                        </div>
                        <p className={styles.previewCardMeta}>
                          {formatHistoryTimestamp(selectedHistoryItem.created_at)}
                        </p>
                      </div>

                      <p className={styles.previewBody}>{getReplyText(selectedHistoryItem)}</p>
                      <p className={styles.previewHint}>{getHistorySummary(selectedHistoryItem)}</p>
                      {selectedHistoryItem.processed_session_id && (
                        <p className={styles.previewFootnote}>
                          Ответ отправлен через сессию {selectedHistoryItem.processed_session_id}.
                        </p>
                      )}
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
                  <h2 id="ai-reply-history-title" className={styles.drawerTitle}>
                    {historyJob.name}
                  </h2>
                  <p className={styles.drawerSubtitle}>
                    Последние решения по сообщениям: reply, skip и ошибки отправки.
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
                    Как только кампания обработает новые сообщения, здесь появятся статусы и ответы.
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
                        onClick={() => setSelectedHistoryItem(item)}
                        aria-pressed={isSelected}
                      >
                        <div className={styles.historyTopRow}>
                          <span
                            className={`${styles.historyStatusBadge} ${
                              item.status === "replied"
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

                        <p className={styles.historyChannel}>{item.chat_name || item.chat_id}</p>
                        <p className={styles.historyMeta}>
                          Сообщение #{item.message_id}
                          {item.reply_message_id ? ` · ответ #${item.reply_message_id}` : ""}
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
                <p className={styles.label}>Чаты</p>
                <p className={styles.helperText}>Выбрано: {form.target_chats.length}</p>
                {loadingChats && <p className={styles.helperText}>Загрузка чатов...</p>}
                {!loadingChats && chatsError && <p className={styles.helperText}>{chatsError}</p>}
                {!loadingChats && form.account_sessions.length === 0 && (
                  <p className={styles.helperText}>Сначала выберите хотя бы один аккаунт.</p>
                )}
                {!loadingChats &&
                  form.account_sessions.length > 0 &&
                  !chatsError &&
                  displayedChats.length === 0 && (
                    <p className={styles.helperText}>Нет доступных чатов для выбранных аккаунтов.</p>
                  )}
                {!loadingChats && displayedChats.length > 0 && (
                  <div className={styles.gridOptions}>
                    {displayedChats.map((chat) => (
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

              <div>
                <label className={styles.label} htmlFor="triggers-input">
                  Триггеры
                </label>
                <p className={styles.helperText}>
                  По одному примеру сообщения на строку. Сейчас: {parseMultilineValues(form.triggers_input).length}
                </p>
                <textarea
                  id="triggers-input"
                  className={styles.textarea}
                  value={form.triggers_input}
                  onChange={(event) =>
                    setForm((currentForm) => ({
                      ...currentForm,
                      triggers_input: event.target.value
                    }))
                  }
                  rows={6}
                  placeholder={"Сколько стоит?\nКак оформить заказ?\nЕсть ли доставка?"}
                  required
                />
              </div>

              <div>
                <label className={styles.label} htmlFor="reply-prompt">
                  Промпт ответа
                </label>
                <textarea
                  id="reply-prompt"
                  className={styles.textarea}
                  value={form.reply_prompt}
                  onChange={(event) =>
                    setForm((currentForm) => ({
                      ...currentForm,
                      reply_prompt: event.target.value
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
                  disabled={saving || sessionsLoading || loadingChats}
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
