const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error("Backend health check failed.");
  }

  return response.json() as Promise<{ status: string }>;
}
