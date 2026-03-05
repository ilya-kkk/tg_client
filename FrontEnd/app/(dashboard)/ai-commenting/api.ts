const API_BASE = "http://localhost:8000";

export type AiCommentJobHistoryStatus = "posted" | "skipped" | "failed";

export interface AiCommentJob {
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

export interface AiCommentJobsResponse extends Array<AiCommentJob> {}

export interface AiCommentJobPost {
  channel_id: string;
  message_id: number;
  comment_message_id: number | null;
  status: AiCommentJobHistoryStatus;
  error: string | null;
  created_at: string;
}

export interface AiCommentJobHistoryResponse extends Array<AiCommentJobPost> {}

interface ApiErrorResponse {
  detail?: string;
  message?: string;
}

export interface AiCommentJobDeleteResponse {
  success: boolean;
}

export interface AiCommentJobCreateRequest {
  name: string;
  account_sessions: string[];
  target_channels: string[];
  user_prompt: string;
  system_prompt: string;
}

export interface AiCommentJobUpdateRequest extends Partial<AiCommentJobCreateRequest> {
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

export function listAiCommentJobs(userId: string): Promise<AiCommentJobsResponse> {
  return fetchJson<AiCommentJobsResponse>(`${API_BASE}/users/${userId}/ai-comment-jobs`);
}

export function createAiCommentJob(
  userId: string,
  payload: AiCommentJobCreateRequest
): Promise<AiCommentJob> {
  return fetchJson<AiCommentJob>(`${API_BASE}/users/${userId}/ai-comment-jobs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateAiCommentJob(
  userId: string,
  jobId: string,
  payload: AiCommentJobUpdateRequest
): Promise<AiCommentJob> {
  return fetchJson<AiCommentJob>(`${API_BASE}/users/${userId}/ai-comment-jobs/${jobId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteAiCommentJob(
  userId: string,
  jobId: string
): Promise<AiCommentJobDeleteResponse> {
  return fetchJson<AiCommentJobDeleteResponse>(`${API_BASE}/users/${userId}/ai-comment-jobs/${jobId}`, {
    method: "DELETE"
  });
}

export function getAiCommentJobHistory(
  userId: string,
  jobId: string
): Promise<AiCommentJobHistoryResponse> {
  return fetchJson<AiCommentJobHistoryResponse>(
    `${API_BASE}/users/${userId}/ai-comment-jobs/${jobId}/history`
  );
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
