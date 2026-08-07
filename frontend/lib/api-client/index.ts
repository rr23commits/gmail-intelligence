const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error("Backend health check failed.");
  }

  return response.json() as Promise<{ status: string }>;
}

export type IntelligenceItem = { id: string; account_id: string; account: string; subject: string; snippet: string; category: string; priority: number; summary: string; at: string };
export type IntelligenceDetail = IntelligenceItem & { messages: { from: string; subject: string | null; body: string; at: string }[] };
export type Account = { id: string; email: string; name: string | null; status: string; last_synced_at: string | null };
async function api<T>(path: string, init?: RequestInit): Promise<T> { const response = await fetch(`${apiBaseUrl}${path}`, init); if (!response.ok) throw new Error(await response.text()); return response.status === 204 ? undefined as T : response.json() as Promise<T>; }
export const getDashboard = () => api<{ items: IntelligenceItem[]; action_required: number; accounts: number }>("/api/v1/dashboard");
export const getIntelligence = () => api<IntelligenceItem[]>("/api/v1/intelligence");
export const getIntelligenceDetail = (id: string) => api<IntelligenceDetail>(`/api/v1/intelligence/${id}`);
export const getAccounts = () => api<Account[]>("/api/v1/accounts");
export const syncAccount = (id: string) => api<void>(`/api/v1/accounts/${id}/sync`, { method: "POST" });
export const deleteAccount = (id: string) => api<void>(`/api/v1/accounts/${id}`, { method: "DELETE" });
export async function connectGmail() { window.location.href = (await api<{ authorization_url: string }>("/api/v1/auth/gmail/start", { method: "POST" })).authorization_url; }
