"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getStoredUser, getToken, logout, type UserInfo } from "@/lib/auth";

const PUBLIC_PATHS = new Set(["/login", "/admin/login", "/register", "/select-profile"]);

export default function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);

  useEffect(() => {
    // Login and profile selection update localStorage before navigating here.
    queueMicrotask(() => setUser(getToken() ? getStoredUser() : null));
  }, [pathname]);

  if (PUBLIC_PATHS.has(pathname) || !user) return null;

  const isManager = user.role === "manager";
  const links = isManager
    ? [{ href: "/", label: "首页" }, { href: "/dashboard", label: "团队看板" }, { href: "/dashboard/assignments", label: "培训任务" }, { href: "/dashboard/knowledge", label: "知识库" }, { href: "/dashboard/feedback", label: "纠错复核" }, { href: "/dashboard/learning", label: "学习验收" }, { href: "/dashboard/operations", label: "运行指标" }, { href: "/dashboard/accounts", label: "账号管理" }]
    : [
        { href: "/", label: "首页" },
        { href: "/profile", label: "我的档案" },
        { href: "/assessment", label: "测评" },
        { href: "/practice", label: "实战练习" },
      ];

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    if (href === "/assessment") return pathname === "/assessment" || pathname === "/post-test";
    if (href === "/dashboard") return pathname === "/dashboard" || pathname.startsWith("/dashboard/members/");
    if (href === "/dashboard/accounts") return pathname === "/dashboard/accounts";
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  function handleLogout() {
    logout();
    setUser(null);
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-slate-950/95 text-slate-100 shadow-sm backdrop-blur-sm">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-4">
        <Link href="/" className="flex items-center gap-2" aria-label="SAGE 首页">
          <span className="text-2xl">🌿</span>
          <span className="font-bold tracking-wide">SAGE</span>
        </Link>
        <nav aria-label="主导航" className="flex max-w-full items-center gap-4 overflow-x-auto whitespace-nowrap text-sm">
          {links.map(link => (
            <Link key={link.href} href={link.href}
              aria-current={isActive(link.href) ? "page" : undefined}
              className={isActive(link.href) ? "font-medium text-emerald-400" : "text-slate-400 transition-colors hover:text-emerald-400"}>
              {link.label}
            </Link>
          ))}
          <span aria-hidden="true" className="text-slate-500">|</span>
          <span className="text-slate-300">{user.display_name || user.username}
            {user.current_profile && (
              <Link href="/select-profile" className="ml-1 text-xs text-emerald-400 hover:underline" title="切换专业方向">
                · {user.current_profile}
              </Link>
            )}
          </span>
          <button type="button" onClick={handleLogout} className="text-slate-400 transition-colors hover:text-rose-400">退出</button>
        </nav>
      </div>
    </header>
  );
}
