const API_BASE = "http://localhost:8000";

export type AiReplyJobHistoryStatus = "replied" | "skipped" | "failed";

export interface AiReplyJob {
  id: string;
  user_id: string;
  name: string;
  account_sessions: string[];
  target_chats: string[];
  triggers: string[];
  reply_prompt: string;
  is_active: boolean;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AiReplyJobMessage {
  chat_id: string;
  chat_name: string | null;
  message_id: number;
  sender_id: number | null;
  message_text: string | null;
  message_date: string | null;
  matched_trigger: string | null;
  reply_message_id: number | null;
  reply_text: string | null;
  processed_session_id: string | null;
  status: AiReplyJobHistoryStatus;
  error: string | null;
  created_at: string;
}

export interface AiReplyJobDeleteResponse {
  success: boolean;
}

export interface AiReplyJobCreateRequest {
  name: string;
  account_sessions: string[];
  target_chats: string[];
  triggers: string[];
  reply_prompt: string;
}

export interface AiReplyJobUpdateRequest extends Partial<AiReplyJobCreateRequest> {
  is_active?: boolean;
}

export interface SessionInfo {
  session_id: string;
  phone: string | null;
  is_authorized: boolean;
}

export interface SessionsResponse {
  success: boolean;
  sessions: SessionInfo[];
  total: number;
}

export interface AccountInfo {
  first_name: string | null;
  phone: string | null;
}

export interface AccountInfoResponse {
  success: boolean;
  account: AccountInfo;
}

export interface ChatInfo {
  id: number;
  name: string;
  type: string | null;
  username: string | null;
}

export interface ChatsResponse {
  success: boolean;
  chats: ChatInfo[];
  total: number;
}

interface ApiErrorResponse {
  detail?: string;
  message?: string;
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

export function listAiReplyJobs(userId: string): Promise<AiReplyJob[]> {
  return fetchJson<AiReplyJob[]>(`${API_BASE}/users/${userId}/ai-reply-jobs`);
}

export function createAiReplyJob(
  userId: string,
  payload: AiReplyJobCreateRequest
): Promise<AiReplyJob> {
  return fetchJson<AiReplyJob>(`${API_BASE}/users/${userId}/ai-reply-jobs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateAiReplyJob(
  userId: string,
  jobId: string,
  payload: AiReplyJobUpdateRequest
): Promise<AiReplyJob> {
  return fetchJson<AiReplyJob>(`${API_BASE}/users/${userId}/ai-reply-jobs/${jobId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteAiReplyJob(
  userId: string,
  jobId: string
): Promise<AiReplyJobDeleteResponse> {
  return fetchJson<AiReplyJobDeleteResponse>(`${API_BASE}/users/${userId}/ai-reply-jobs/${jobId}`, {
    method: "DELETE"
  });
}

export function getAiReplyJobHistory(
  userId: string,
  jobId: string
): Promise<AiReplyJobMessage[]> {
  return fetchJson<AiReplyJobMessage[]>(`${API_BASE}/users/${userId}/ai-reply-jobs/${jobId}/history`);
}

export function listSessions(): Promise<SessionsResponse> {
  return fetchJson<SessionsResponse>(`${API_BASE}/sessions`);
}

export function getSessionAccount(sessionId: string): Promise<AccountInfoResponse> {
  return fetchJson<AccountInfoResponse>(`${API_BASE}/sessions/${sessionId}/account/me`);
}

export function listSessionChats(sessionId: string, limit: number): Promise<ChatsResponse> {
  return fetchJson<ChatsResponse>(`${API_BASE}/sessions/${sessionId}/chats?limit=${limit}`);
}
