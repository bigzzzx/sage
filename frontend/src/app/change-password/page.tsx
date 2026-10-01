"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { changeOwnPassword } from "@/lib/api";
import { getStoredUser, logout } from "@/lib/auth";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (!getStoredUser()) router.replace("/login"); }, [router]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      await changeOwnPassword(current, next);
      const role = getStoredUser()?.role;
      logout();
      router.replace(role === "manager" ? "/admin/login?password-reset=1" : "/login");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "修改失败"); }
    finally { setSaving(false); }
  }
  return <main className="min-h-screen bg-slate-900 px-4 py-16 text-slate-100"><div className="mx-auto max-w-md rounded-xl border border-slate-700 bg-slate-800 p-7"><h1 className="text-2xl font-bold">设置个人密码</h1><p className="mt-2 text-sm text-slate-400">首次登录或管理员重置密码后，需先设置自己的密码。完成后请重新登录。</p><form onSubmit={submit} className="mt-6 space-y-4"><label className="block text-sm">当前或初始密码<input required type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} className="mt-1 w-full rounded border border-slate-600 bg-slate-950 px-3 py-2" /></label><label className="block text-sm">新密码（至少 12 位）<input required minLength={12} type="password" autoComplete="new-password" value={next} onChange={e => setNext(e.target.value)} className="mt-1 w-full rounded border border-slate-600 bg-slate-950 px-3 py-2" /></label>{error && <p role="alert" className="text-sm text-rose-300">{error}</p>}<button disabled={saving} className="w-full rounded bg-emerald-700 py-2 font-semibold disabled:opacity-50">{saving ? "保存中…" : "修改并重新登录"}</button></form></div></main>;
}
