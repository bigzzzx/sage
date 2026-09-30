"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { fetchRegistrationEnabled, login, logout } from "@/lib/auth";

export default function LoginForm({ adminMode = false }: { adminMode?: boolean }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    if (adminMode && new URLSearchParams(window.location.search).get("password-reset") === "1") {
      queueMicrotask(() => setNotice("密码已更新，请使用新密码登录。"));
    }
    if (!adminMode) fetchRegistrationEnabled().then(setRegistrationEnabled).catch(() => setRegistrationEnabled(null));
  }, [adminMode]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user = await login(username, password);
      if (adminMode && user.role !== "manager") {
        logout();
        setError("该账号没有管理员权限。普通成员请使用成员登录入口。");
        return;
      }
      router.push(user.must_change_password ? "/change-password" : user.role === "manager" ? "/dashboard" : "/select-profile");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 flex items-center justify-center px-4">
      <div className="sage-content sage-content--auth w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-2">
            <span className="text-4xl">🌿</span>
            <span className="text-3xl font-bold text-slate-100 tracking-wide">SAGE</span>
          </div>
          <p className="text-slate-400 text-sm">{adminMode ? "管理员登录" : "SE Adaptive Growth Engine"}</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-slate-800/60 border border-slate-700 rounded-xl p-6 space-y-5">
          {adminMode && <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-xs leading-5 text-emerald-200">管理员账号由现有管理员创建；首次管理员由部署者初始化。</div>}
          {notice && <p role="status" className="text-center text-sm text-emerald-300">{notice}</p>}
          <div>
            <label htmlFor="username" className="block text-sm text-slate-300 mb-1.5">用户名</label>
            <input id="username" type="text" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus
              autoComplete="username" className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors" placeholder="请输入用户名" />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm text-slate-300 mb-1.5">密码</label>
            <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password"
              className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors" placeholder="请输入密码" />
          </div>
          {error && <p role="alert" className="text-rose-400 text-sm text-center">{error}</p>}
          <button type="submit" disabled={loading || !username || !password}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold rounded-lg transition-colors">
            {loading ? "登录中…" : adminMode ? "进入管理员面板" : "登录"}
          </button>
          {adminMode ? <p className="text-center text-sm text-slate-400"><Link href="/login" className="text-emerald-400 hover:text-emerald-300">返回成员登录</Link></p> : <>
            {registrationEnabled === true && <p className="text-center text-sm text-slate-400">还没有账号？{" "}<Link href="/register" className="text-emerald-400 hover:text-emerald-300">注册</Link></p>}
            {registrationEnabled === false && <p className="text-center text-xs text-slate-500">新账号请联系管理员创建</p>}
            <p className="text-center text-sm"><Link href="/admin/login" className="text-slate-400 hover:text-emerald-300">管理员入口 →</Link></p>
          </>}
        </form>
      </div>
    </main>
  );
}
