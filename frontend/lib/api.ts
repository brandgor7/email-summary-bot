import axios from "axios";

let cachedToken: string | null = null;
let tokenExpiry = 0;

async function getBackendToken(): Promise<string> {
  const now = Date.now();
  if (cachedToken && now < tokenExpiry - 60_000) {
    return cachedToken;
  }
  const res = await fetch("/api/auth/token");
  if (!res.ok) throw new Error("Not authenticated");
  const data = await res.json();
  cachedToken = data.token as string;
  tokenExpiry = now + 55 * 60 * 1000; // 55 min (token expires in 1h)
  return cachedToken;
}

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
});

api.interceptors.request.use(async (config) => {
  const token = await getBackendToken();
  config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export default api;
