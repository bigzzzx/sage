"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchProfiles, getStoredUser, switchProfile, type Profile } from "@/lib/auth";

export default function SelectProfilePage() {
  const router = useRouter();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const user = getStoredUser();
    if (!user) {
      router.push("/login");
      return;
    }
    fetchProfiles()
      .then(setProfiles)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [router]);

  async function handleSelect(profile: Profile) {
    if (!profile.available) return;
    setSwitching(profile.id);
    setError(null);
    try {
      await switchProfile(profile.id);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "切换失败");
      setSwitching(null);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 flex flex-col items-center justify-center px-6 py-12">
      <div className="sage-content sage-content--narrow w-full max-w-3xl">
        <h1 className="sage-page-title text-3xl font-bold text-slate-100 text-center mb-2">
          选择你的专业方向
        </h1>
        <p className="sage-page-description mx-auto text-slate-400 text-center mb-10 text-sm">
          选择一个方向开始你的能力成长之旅
        </p>

        {error && (
          <p className="text-rose-400 text-sm text-center mb-4">{error}</p>
        )}

        {loading ? (
          <p className="text-slate-400 text-center">加载中…</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {profiles.map((profile) => {
              const isAvailable = profile.available;
              const isSwitching = switching === profile.id;
              return (
                <button
                  key={profile.id}
                  onClick={() => handleSelect(profile)}
                  disabled={!isAvailable || !!switching}
                  className={`relative p-6 rounded-xl border-2 text-center transition-all ${
                    isAvailable
                      ? "bg-slate-800/60 border-emerald-500/60 hover:border-emerald-400 hover:bg-slate-800 cursor-pointer"
                      : "bg-slate-800/30 border-slate-700 cursor-not-allowed opacity-60"
                  }`}
                >
                  <div className="text-4xl mb-3">{profile.icon}</div>
                  <div className={`font-semibold text-lg ${isAvailable ? "text-slate-100" : "text-slate-500"}`}>
                    {profile.name}
                  </div>
                  {!isAvailable && (
                    <span className="absolute top-3 right-3 text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded">
                      敬请期待
                    </span>
                  )}
                  {isSwitching && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-900/60 rounded-xl">
                      <span className="text-emerald-400 text-sm">切换中…</span>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
