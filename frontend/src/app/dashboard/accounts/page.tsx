"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser, logout } from "@/lib/auth";
import { changeOwnPassword, createAdminAccount, fetchAdminAccounts, fetchAdminAudit, fetchEnrollments, resetAdminAccountPassword, setEnrollment, updateAdminAccountStatus, type AdminAccount, type AdminAuditItem } from "@/lib/api";

function errorMessage(error: unknown) { return error instanceof Error ? error.message : "操作失败，请稍后重试"; }

export default function AdminAccountsPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<ReturnType<typeof getStoredUser>>(null);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"member" | "manager">("member");
  const [resetTarget, setResetTarget] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [oldOwnPassword, setOldOwnPassword] = useState("");
  const [newOwnPassword, setNewOwnPassword] = useState("");
  const [audit, setAudit] = useState<AdminAuditItem[]>([]);
  const [enrollments, setEnrollments] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [page, setPage] = useState(0);
  const filtered = accounts.filter(account => (roleFilter === "all" || account.role === roleFilter) &&
    `${account.username} ${account.display_name}`.toLowerCase().includes(query.trim().toLowerCase()));
  const visible = filtered.slice(page * 10, page * 10 + 10);
  const activeProfile = currentUser?.current_profile || "big_data";

  const refresh = useCallback(async (profile = activeProfile) => {
    setLoading(true); setError("");
    try { const [users, changes, roster] = await Promise.all([fetchAdminAccounts(), fetchAdminAudit(), fetchEnrollments(profile)]); setAccounts(users); setAudit(changes); setEnrollments(roster); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => {
    const user = getStoredUser();
    if (!user) { router.replace("/admin/login"); return; }
    if (user.role !== "manager") { router.replace("/"); return; }
    queueMicrotask(() => {
      setCurrentUser(user);
      void refresh(user.current_profile || "big_data");
    });
  }, [router, refresh]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setNotice("");
    try {
      await createAdminAccount({ username, display_name: displayName, password, role });
      setUsername(""); setDisplayName(""); setPassword(""); setRole("member");
      setNotice("账号已创建。请通过安全渠道将用户名和初始密码交给使用者。");
      await refresh();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setSaving(false); }
  }

  async function handleReset(user: AdminAccount) {
    if (resetPassword.length < 12) { setError("新密码至少需要 12 位"); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      await resetAdminAccountPassword(user.user_id, resetPassword);
      setResetPassword(""); setResetTarget(null);
      if (user.user_id === currentUser?.user_id) {
        logout(); router.replace("/admin/login?password-reset=1"); return;
      }
      setNotice(`${user.username} 的密码已重置，原有登录会话已全部失效。请通过安全渠道告知新密码。`);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setSaving(false); }
  }

  async function handleStatus(account: AdminAccount, input: { is_active?: boolean; is_demo?: boolean }) {
    setSaving(true); setError(""); setNotice("");
    try {
      await updateAdminAccountStatus(account.user_id, input);
      await refresh();
      setNotice("账号状态已更新。停用账号会立即使其已有登录会话失效。");
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setSaving(false); }
  }

  async function handleOwnPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      await changeOwnPassword(oldOwnPassword, newOwnPassword);
      setOldOwnPassword(""); setNewOwnPassword("");
      logout(); router.replace("/admin/login?password-reset=1");
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setSaving(false); }
  }

  async function handleEnrollment(account: AdminAccount) {
    setSaving(true); setError("");
    try { await setEnrollment(account.user_id, currentUser?.current_profile || "big_data", !enrollments.includes(account.user_id)); await refresh(); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setSaving(false); }
  }

  return (
    <main className="min-h-screen bg-slate-900 px-4 py-10 text-slate-100">
      <div className="sage-content mx-auto max-w-5xl space-y-7">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div><p className="text-xs tracking-[0.2em] text-emerald-400">ADMINISTRATION</p><h1 className="mt-2 text-3xl font-bold">账号管理</h1><p className="mt-2 text-sm text-slate-400">创建成员或管理员账号，并在需要时重置密码。</p></div>
          <Link href="/dashboard" className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:border-emerald-600">← 返回团队看板</Link>
        </header>
        {error && <p role="alert" className="rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-300">{error}</p>}
        {notice && <p role="status" className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-sm text-emerald-300">{notice}</p>}

        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-6">
          <h2 className="text-xl font-semibold">创建账号</h2>
          <p className="mt-1 text-sm text-slate-400">管理员权限只由已登录管理员授予。密码至少 12 位，创建后请通过安全渠道交付。</p>
          <form onSubmit={handleCreate} className="mt-5 grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-300">用户名<input required minLength={2} maxLength={32} pattern="[A-Za-z0-9_]+" autoComplete="off" value={username} onChange={e => setUsername(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5" placeholder="字母、数字或下划线" /></label>
            <label className="text-sm text-slate-300">显示名称<input maxLength={64} value={displayName} onChange={e => setDisplayName(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5" placeholder="可选" /></label>
            <label className="text-sm text-slate-300">初始密码<input required minLength={12} type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5" placeholder="至少 12 位" /></label>
            <label className="text-sm text-slate-300">账号角色<select value={role} onChange={e => setRole(e.target.value as "member" | "manager")} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5"><option value="member">成员</option><option value="manager">管理员</option></select></label>
            <button disabled={saving} className="rounded-lg bg-emerald-600 px-4 py-3 font-semibold hover:bg-emerald-500 disabled:opacity-50 md:col-span-2">{saving ? "正在保存…" : "创建账号"}</button>
          </form>
        </section>
        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-6"><h2 className="text-xl font-semibold">修改我的密码</h2><p className="mt-1 text-sm text-slate-400">修改成功后全部会话失效，需要重新登录。</p><form onSubmit={handleOwnPassword} className="mt-4 flex flex-wrap gap-3"><input required type="password" autoComplete="current-password" value={oldOwnPassword} onChange={e => setOldOwnPassword(e.target.value)} placeholder="当前密码" className="rounded border border-slate-700 bg-slate-950 px-3 py-2" /><input required minLength={12} type="password" autoComplete="new-password" value={newOwnPassword} onChange={e => setNewOwnPassword(e.target.value)} placeholder="新密码（至少12位）" className="rounded border border-slate-700 bg-slate-950 px-3 py-2" /><button disabled={saving} className="rounded bg-emerald-700 px-4 py-2 disabled:opacity-50">修改密码</button></form></section>
        <section className="rounded-xl border border-slate-800 bg-slate-900/70 p-6"><h2 className="text-xl font-semibold">最近账号操作</h2><div className="mt-3 max-h-64 space-y-2 overflow-auto text-sm">{audit.map((item, index) => <p key={`${item.created_at}-${index}`} className="border-b border-slate-800 pb-2 text-slate-300">{new Date(item.created_at).toLocaleString("zh-CN")} · {item.action} · 操作人 {accounts.find(account => account.user_id === item.actor_id)?.username || item.actor_id} · 目标 {accounts.find(account => account.user_id === item.target_id)?.username || item.target_id} {item.detail}</p>)}{audit.length === 0 && <p className="text-slate-400">暂无操作记录；历史变更不会补录。</p>}</div></section>

        <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/70">
          <div className="flex items-center justify-between border-b border-slate-800 p-5"><div><h2 className="text-xl font-semibold">现有账号</h2><p className="mt-1 text-sm text-slate-400">账号全局共通；{currentUser?.current_profile || "big_data"} 培训名单单独维护 · 共 {accounts.length} 个账号，符合筛选 {filtered.length} 个</p></div><button onClick={() => void refresh()} className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:border-emerald-600">刷新</button></div>
          <div className="flex gap-3 border-b border-slate-800 p-5"><input value={query} onChange={e => { setQuery(e.target.value); setPage(0); }} placeholder="搜索用户名或显示名称" className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm" /><select value={roleFilter} onChange={e => { setRoleFilter(e.target.value); setPage(0); }} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="all">全部角色</option><option value="member">成员</option><option value="manager">管理员</option></select></div>
          {loading ? <p className="p-8 text-center text-slate-400">正在读取账号…</p> : filtered.length === 0 ? <p className="p-8 text-center text-slate-400">没有符合条件的账号</p> : <div className="divide-y divide-slate-800">
            {visible.map(account => <div key={account.user_id} className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><p className="font-medium">{account.display_name || account.username} <span className="ml-2 text-sm text-slate-400">@{account.username}</span>{account.user_id === currentUser?.user_id && <span className="ml-2 text-xs text-emerald-300">当前账号</span>}</p><p className="mt-1 text-xs text-slate-500">{account.role === "manager" ? "管理员" : "成员"} · {account.is_active ? "启用" : "已停用"} · {account.is_demo ? "样例账号" : "正式账号"} {account.must_change_password ? "· 待修改初始密码" : ""} · 创建于 {account.created_at ? new Date(account.created_at).toLocaleDateString("zh-CN") : "—"}</p></div>
                <div className="flex flex-wrap gap-2">{account.role === "member" && <button disabled={saving} onClick={() => void handleEnrollment(account)} className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:border-emerald-600">{enrollments.includes(account.user_id) ? "移出培训" : "纳入培训"}</button>}<button disabled={saving} onClick={() => void handleStatus(account, { is_demo: !account.is_demo })} className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:border-amber-600">{account.is_demo ? "标为正式" : "标为样例"}</button><button disabled={saving || account.user_id === currentUser?.user_id} onClick={() => void handleStatus(account, { is_active: !account.is_active })} className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:border-rose-600">{account.is_active ? "停用" : "恢复"}</button><button onClick={() => { setResetTarget(resetTarget === account.user_id ? null : account.user_id); setResetPassword(""); setError(""); }} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-amber-600">重置密码</button></div>
              </div>
              {resetTarget === account.user_id && <div className="mt-4 flex flex-col gap-2 sm:flex-row"><input type="password" autoComplete="new-password" minLength={12} value={resetPassword} onChange={e => setResetPassword(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" placeholder="输入至少 12 位新密码" /><button disabled={saving || resetPassword.length < 12} onClick={() => void handleReset(account)} className="rounded-lg bg-amber-700 px-4 py-2 text-sm font-medium hover:bg-amber-600 disabled:opacity-50">确认重置</button></div>}
            </div>)}
          </div>}
          {filtered.length > 10 && <div className="flex items-center justify-between border-t border-slate-800 p-4 text-sm"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.ceil(filtered.length / 10)}</span><button disabled={(page + 1) * 10 >= filtered.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
        </section>
      </div>
    </main>
  );
}
