/**
 * Auth utilities — localStorage-based, no context/provider needed.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "sage_token";
const USER_KEY = "sage_user";

export interface UserInfo {
  user_id: string;
  username: string;
  display_name: string;
  role: string;
  current_profile?: string;
}

export interface Profile {
  id: string;
  name: string;
  icon: string;
  available: boolean;
}

// ---------- Token ----------

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// ---------- User ----------

export function getStoredUser(): UserInfo | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserInfo;
  } catch {
    return null;
  }
}

export function setStoredUser(user: UserInfo) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearStoredUser() {
  localStorage.removeItem(USER_KEY);
}

// ---------- Auth check ----------

export function isLoggedIn(): boolean {
  return !!getToken() && !!getStoredUser();
}

// ---------- API calls ----------

export async function register(username: string, password: string, displayName?: string): Promise<UserInfo> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName || "" }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "注册失败");
  }
  const data = await res.json();
  setToken(data.token);
  const user: UserInfo = {
    user_id: data.user_id,
    username: data.username,
    display_name: data.display_name,
    role: data.role,
    current_profile: data.current_profile || "",
  };
  setStoredUser(user);
  return user;
}

export async function login(username: string, password: string): Promise<UserInfo> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "登录失败");
  }
  const data = await res.json();
  setToken(data.token);
  const user: UserInfo = {
    user_id: data.user_id,
    username: data.username,
    display_name: data.display_name,
    role: data.role,
    current_profile: data.current_profile || "",
  };
  setStoredUser(user);
  return user;
}

export async function fetchMe(): Promise<UserInfo> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("获取用户信息失败");
  const data = await res.json();
  const user: UserInfo = {
    user_id: data.user_id,
    username: data.username,
    display_name: data.display_name,
    role: data.role,
    current_profile: data.current_profile || "",
  };
  setStoredUser(user);
  return user;
}

export async function fetchProfiles(): Promise<Profile[]> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/profiles`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("获取专业方向列表失败");
  const data = await res.json();
  return data.profiles;
}

export async function switchProfile(profileId: string): Promise<UserInfo> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/profile`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ profile_id: profileId }),
  });
  if (!res.ok) throw new Error("切换专业方向失败");
  // Update stored user with new profile id
  const user = getStoredUser();
  if (user) {
    user.current_profile = profileId;
    setStoredUser(user);
  }
  return user!;
}

export function logout() {
  clearToken();
  clearStoredUser();
}
