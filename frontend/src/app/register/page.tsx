"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { fetchRegistrationEnabled, register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    fetchRegistrationEnabled().then(setRegistrationEnabled).catch(() => setRegistrationEnabled(null));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (registrationEnabled !== true) { setError("当前不开放自助注册，请联系管理员"); return; }

    if (password !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    if (password.length < 6) {
      setError("密码长度不能少于 6 位");
      return;
    }

    setLoading(true);
    try {
      await register(username, password, displayName || undefined);
      router.push("/select-profile");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 flex items-center justify-center px-4">
      <div className="sage-content sage-content--auth w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-2">
            <span className="text-4xl">🌿</span>
            <span className="text-3xl font-bold text-slate-100 tracking-wide">SAGE</span>
          </div>
          <p className="text-slate-400 text-sm">创建你的账号</p>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="bg-slate-800/60 border border-slate-700 rounded-xl p-6 space-y-5"
        >
          <div>
            <label htmlFor="username" className="block text-sm text-slate-300 mb-1.5">
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              minLength={2}
              maxLength={32}
              className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="2-32 个字符"
            />
          </div>

          <div>
            <label htmlFor="displayName" className="block text-sm text-slate-300 mb-1.5">
              显示名称 <span className="text-slate-500">（选填）</span>
            </label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="不填则默认使用用户名"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm text-slate-300 mb-1.5">
              密码
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="至少 6 位"
            />
          </div>

          <div>
            <label htmlFor="confirmPassword" className="block text-sm text-slate-300 mb-1.5">
              确认密码
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
              placeholder="再次输入密码"
            />
          </div>

          {error && (
            <p className="text-rose-400 text-sm text-center">{error}</p>
          )}
          {registrationEnabled === false && <p className="text-amber-300 text-sm text-center">当前由管理员统一创建账号</p>}

          <button
            type="submit"
            disabled={registrationEnabled !== true || loading || !username || !password || !confirmPassword}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold rounded-lg transition-colors"
          >
            {loading ? "注册中…" : "注册"}
          </button>

          <p className="text-center text-sm text-slate-400">
            已有账号？{" "}
            <Link href="/login" className="text-emerald-400 hover:text-emerald-300 transition-colors">
              登录
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
