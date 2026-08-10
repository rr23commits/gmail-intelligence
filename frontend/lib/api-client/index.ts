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
export type IntelligenceItem = { id: string; account_id: string; account: string; subject: string; snippet: string; category: string; priority: number; confidence: number; summary: string; at: string; is_unread: boolean };
export type IntelligenceDetail = IntelligenceItem & { explanation: IntelligenceExplanation; classifier_version: string; gmail_url: string; messages: { from: string; subject: string | null; body: string; at: string }[] };
export type IntelligenceOverview = { total_analyzed: number; categories: Record<string, number>; needs_attention: number; low_priority: number; promotional: number; notifications: number };
export type CleanupGroup = { key: string; title: string; description: string; items: IntelligenceItem[] };
export type Cleanup = { total_impact: number; groups: CleanupGroup[] };
export type Account = { id: string; email: string; name: string | null; status: string; last_synced_at: string | null };
async function api<T>(path: string, init?: RequestInit): Promise<T> { const response = await fetch(`${apiBaseUrl}${path}`, init); if (!response.ok) throw new Error(await response.text()); return response.status === 204 ? undefined as T : response.json() as Promise<T>; }
export const getDashboard = () => api<{ items: IntelligenceItem[]; action_required: number; accounts: number }>("/api/v1/dashboard");
export type IntelligenceFilter = { accountId?: string; category?: string; review?: boolean };
export const getIntelligence = (filter: IntelligenceFilter = {}) => {
  const params = new URLSearchParams();
  if (filter.accountId) params.set("account_id", filter.accountId);
  if (filter.category) params.set("category", filter.category);
  if (filter.review) params.set("review", "true");
  const query = params.size ? `?${params}` : "";
  return api<IntelligenceItem[]>(`/api/v1/intelligence${query}`);
};
export const getIntelligenceDetail = (id: string) => api<IntelligenceDetail>(`/api/v1/intelligence/${id}`);
export const getIntelligenceOverview = (accountId?: string) => api<IntelligenceOverview>(`/api/v1/intelligence/overview${accountId ? `?account_id=${accountId}` : ""}`);
export const getCleanup = (accountId?: string) => api<Cleanup>(`/api/v1/intelligence/cleanup${accountId ? `?account_id=${accountId}` : ""}`);
export const correctClassification = (id: string, correctedCategory: string) => api<IntelligenceItem>(`/api/v1/intelligence/${id}/classification-feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ corrected_category: correctedCategory }) });
export const applyThreadAction = (accountId: string, action: "archive" | "delete" | "mark_read" | "mark_unread", threadIds: string[]) => api<{ updated: number }>(`/api/v1/accounts/${accountId}/threads/action`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, thread_ids: threadIds }) });
export const replyToThread = (accountId: string, threadId: string, body: string) => api<{ sent: boolean }>(`/api/v1/accounts/${accountId}/threads/${threadId}/reply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }) });
export const getAccounts = () => api<Account[]>("/api/v1/accounts");
export const syncAccount = (id: string) => api<void>(`/api/v1/accounts/${id}/sync`, { method: "POST" });
export const deleteAccount = (id: string) => api<void>(`/api/v1/accounts/${id}`, { method: "DELETE" });
export async function connectGmail() { window.location.href = (await api<{ authorization_url: string }>("/api/v1/auth/gmail/start", { method: "POST" })).authorization_url; }
