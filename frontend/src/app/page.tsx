"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser, logout, type UserInfo } from "@/lib/auth";

export default function Home() {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);

  useEffect(() => {
    const stored = getStoredUser();
    if (!stored) {
      router.push("/login");
      return;
    }
    setUser(stored);
  }, [router]);

  function handleLogout() {
    logout();
    router.push("/login");
  }

  if (!user) return null;

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-slate-100 flex flex-col">
      {/* 顶部导航 */}
      <nav className="border-b border-slate-800/60 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🌿</span>
            <span className="font-bold tracking-wide">SAGE</span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            {user.role === "manager" ? (
              <Link
                href="/dashboard"
                className="text-slate-400 hover:text-emerald-400 transition-colors"
              >
                团队看板
              </Link>
            ) : (
              <>
                <Link
                  href="/profile"
                  className="text-slate-400 hover:text-emerald-400 transition-colors"
                >
                  我的档案
                </Link>
                <Link
                  href="/assessment"
                  className="text-slate-400 hover:text-emerald-400 transition-colors"
                >
                  测评
                </Link>
              </>
            )}
            <span className="text-slate-500">|</span>
            <span className="text-slate-300">
              {user.display_name}
              {user.current_profile && (
                <Link
                  href="/select-profile"
                  className="text-emerald-400 ml-1 text-xs hover:underline"
                  title="切换专业方向"
                >
                  · {user.current_profile}
                </Link>
              )}
            </span>
            <button
              onClick={handleLogout}
              className="text-slate-400 hover:text-rose-400 transition-colors"
            >
              退出
            </button>
          </div>
        </div>
      </nav>

      {/* 中央主体 */}
      <section className="flex-1 flex flex-col items-center justify-center px-6 -mt-12">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-5xl">🌿</span>
          <h1 className="text-6xl font-bold tracking-tight">SAGE</h1>
        </div>
        <p className="text-slate-400 text-sm mb-12 tracking-wide">
          SE Adaptive Growth Engine
        </p>

        <div className="flex flex-col sm:flex-row gap-4">
          {user.role === "manager" ? (
            <Link
              href="/dashboard"
              className="px-8 py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg transition-colors shadow-lg shadow-emerald-500/20"
            >
              团队看板
            </Link>
          ) : (
            <>
              <Link
                href="/assessment"
                className="px-8 py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg transition-colors shadow-lg shadow-emerald-500/20"
              >
                开始测评
              </Link>
              <Link
                href="/profile"
                className="px-8 py-3 bg-slate-800/60 hover:bg-slate-700 border border-slate-700 text-white font-medium rounded-lg transition-colors"
              >
                我的档案
              </Link>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
