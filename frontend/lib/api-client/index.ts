const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error("Backend health check failed.");
  }

  return response.json() as Promise<{ status: string }>;
}

export type IntelligenceReason = { signal: string; label: string; points: number };
export type IntelligenceExplanation = { summary: string; category: { selected: string; tie_breaker: string }; reasons: IntelligenceReason[]; priority_breakdown: Record<string, number>; confidence: { value: number; factors: string[] }; classifier_version: string };
export type IntelligenceItem = { id: string; account_id: string; account: string; subject: string; snippet: string; category: string; decision: string; priority: number; confidence: number; summary: string; at: string; is_unread: boolean };
export type ActionTask = { id: string; title: string; deadline: string | null; status: "open" | "done" | "snoozed"; source_thread_id: string; source_message_id: string };
export type DailyTask = ActionTask & { account_id: string; account: string; priority: number; latest_event: string | null; open_action: string };
export type DailyBriefing = { tasks: DailyTask[]; consider: IntelligenceItem[]; consider_count: number; cleanup_count: number };
export type IntelligenceDetail = IntelligenceItem & { explanation: IntelligenceExplanation; classifier_version: string; gmail_url: string; categories: string[]; messages: { id: string; thread_id: string; from: string; subject: string | null; body: string; at: string; is_current: boolean }[]; thread_intelligence: { state: string; latest_event: string | null; open_action: string | null; explicit_deadline: string | null }; task: ActionTask | null };
export type IntelligenceOverview = { total_analyzed: number; categories: Record<string, number>; needs_attention: number; opportunities: number; important: number; low_priority: number; promotional: number; notifications: number; decisions: Record<string, number> };
export type SenderGroup = { sender: string; total: number; categories: Record<string, number>; decisions: Record<string, number> };
export type LearnedPreference = { domain: string; original_category: string; learned_category: string; correction_count: number };
export type CleanupGroup = { key: string; title: string; description: string; items: IntelligenceItem[] };
export type Cleanup = { total_impact: number; groups: CleanupGroup[]; next_offset: number | null };
export type Account = { id: string; email: string; name: string | null; status: string; last_synced_at: string | null };
export type SyncRun = { status: string; started_at: string; completed_at: string | null; messages_examined: number; messages_imported: number; error_code: string | null; error_summary: string | null };
async function api<T>(path: string, init?: RequestInit): Promise<T> { const response = await fetch(`${apiBaseUrl}${path}`, { credentials: "include", ...init }); if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || "Request failed."); } return response.status === 204 ? undefined as T : response.json() as Promise<T>; }
export const getSession = () => api<{ email: string }>("/api/v1/auth/session");
export const login = (password: string) => api<void>("/api/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
export const logout = () => api<void>("/api/v1/auth/logout", { method: "POST" });
export const getDashboard = (accountId?: string) => api<DailyBriefing>(`/api/v1/dashboard${accountId ? `?account_id=${accountId}` : ""}`);
export type IntelligenceFilter = { accountId?: string; category?: string; review?: boolean; decision?: string; limit?: number; offset?: number };
export const getIntelligence = (filter: IntelligenceFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.accountId) params.set("account_id", filter.accountId);
  if (filter.category) params.set("category", filter.category);
  if (filter.review) params.set("review", "true");
  if (filter.decision) params.set("decision", filter.decision);
  if (filter.limit) params.set("limit", String(filter.limit));
  if (filter.offset) params.set("offset", String(filter.offset));
  const query = params.size ? `?${params}` : "";
  return api<IntelligenceItem[]>(`/api/v1/intelligence${query}`);
};
export const getIntelligenceDetail = (id: string, messageId?: string) => api<IntelligenceDetail>(`/api/v1/intelligence/${id}${messageId ? `?message_id=${messageId}` : ""}`);
export const getIntelligenceOverview = (accountId?: string) => api<IntelligenceOverview>(`/api/v1/intelligence/overview${accountId ? `?account_id=${accountId}` : ""}`);
export const getSenderGroups = (accountId?: string) => api<SenderGroup[]>(`/api/v1/intelligence/senders${accountId ? `?account_id=${accountId}` : ""}`);
export const getLearnedPreferences = (accountId: string) => api<LearnedPreference[]>(`/api/v1/intelligence/learned-preferences?account_id=${accountId}`);
export const getCleanup = (accountId?: string, offset = 0, limit = 100) => api<Cleanup>(`/api/v1/intelligence/cleanup?${new URLSearchParams({ ...(accountId ? { account_id: accountId } : {}), offset: String(offset), limit: String(limit) })}`);
export const correctClassification = (id: string, correctedCategory: string) => api<IntelligenceItem>(`/api/v1/intelligence/${id}/classification-feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ corrected_category: correctedCategory }) });
export const applyThreadAction = (accountId: string, action: "archive" | "delete" | "mark_read" | "mark_unread", threadIds: string[]) => api<{ updated: number }>(`/api/v1/accounts/${accountId}/threads/action`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, thread_ids: threadIds }) });
export const replyToThread = (accountId: string, threadId: string, body: string) => api<{ sent: boolean }>(`/api/v1/accounts/${accountId}/threads/${threadId}/reply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }) });
export const updateTaskStatus = (accountId: string, taskId: string, status: ActionTask["status"]) => api<ActionTask>(`/api/v1/accounts/${accountId}/tasks/${taskId}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
let accountsRequest: Promise<Account[]> | null = null;
export const getAccounts = (refresh = false) => {
  if (refresh) accountsRequest = null;
  return accountsRequest ??= api<Account[]>("/api/v1/accounts");
};
export const getSyncRuns = (accountId: string) => api<SyncRun[]>(`/api/v1/accounts/${accountId}/sync-runs`);
export const syncAccount = (id: string) => api<void>(`/api/v1/accounts/${id}/sync`, { method: "POST" });
export const deleteAccount = (id: string) => api<void>(`/api/v1/accounts/${id}`, { method: "DELETE" });
export async function connectGmail() { window.location.href = (await api<{ authorization_url: string }>("/api/v1/auth/gmail/start", { method: "POST" })).authorization_url; }
