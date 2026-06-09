"use client";

import { useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";
import api from "@/lib/api";
import type { LinkCodeResponse, ProvidersResponse, TelegramStatusResponse } from "@/types";

type Step = 1 | 2 | 3;

function OnboardContent() {
  const { status } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [step, setStep] = useState<Step>(1);
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [outlookConnected, setOutlookConnected] = useState(false);
  const [telegramLinked, setTelegramLinked] = useState(false);
  const [linkCode, setLinkCode] = useState<LinkCodeResponse | null>(null);
  const [digestPrefs, setDigestPrefs] = useState("");
  const [schedule, setSchedule] = useState<"morning" | "evening" | "both">("morning");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/providers`)
      .then((r) => r.json())
      .then(setProviders)
      .catch(() => null);
  }, []);

  // On mount, fetch current settings and check connection status
  useEffect(() => {
    if (status !== "authenticated") return;
    api.get("/users/me/settings").then((r) => {
      setDigestPrefs(r.data.digest_prefs);
      setSchedule(r.data.schedule);
    }).catch(() => null);
  }, [status]);

  // Handle OAuth redirect return
  useEffect(() => {
    const oauth = searchParams.get("oauth");
    const oauthStatus = searchParams.get("status");
    if (oauth === "outlook" && oauthStatus === "connected") {
      setOutlookConnected(true);
      setStep(2);
    }
  }, [searchParams]);

  async function connectOutlook() {
    setError(null);
    try {
      const res = await api.get("/auth/outlook/url");
      window.location.href = res.data.url;
    } catch {
      setError("Failed to get Outlook authorization URL.");
    }
  }

  async function getTelegramCode() {
    setError(null);
    try {
      const res = await api.post<LinkCodeResponse>("/destinations/telegram/link-code");
      setLinkCode(res.data);
      pollTelegramStatus();
    } catch {
      setError("Failed to generate Telegram link code.");
    }
  }

  function pollTelegramStatus() {
    const interval = setInterval(async () => {
      try {
        const res = await api.get<TelegramStatusResponse>("/destinations/telegram/status");
        if (res.data.linked) {
          setTelegramLinked(true);
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    setTimeout(() => clearInterval(interval), 10 * 60 * 1000);
  }

  async function savePreferences() {
    setSaving(true);
    setError(null);
    try {
      await api.put("/users/me/settings", { digest_prefs: digestPrefs, schedule });
      router.push("/settings");
    } catch {
      setError("Failed to save preferences.");
    } finally {
      setSaving(false);
    }
  }

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="text-4xl mb-3">📬</div>
          <h1 className="text-2xl font-bold text-gray-900">Set up your digest</h1>
          <p className="text-gray-500 mt-1">Just a few steps to get started</p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {([1, 2, 3] as const).map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                  step === s
                    ? "bg-blue-600 text-white"
                    : step > s
                    ? "bg-green-500 text-white"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {step > s ? "✓" : s}
              </div>
              {s < 3 && <div className={`w-12 h-0.5 ${step > s ? "bg-green-500" : "bg-gray-200"}`} />}
            </div>
          ))}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 mb-6 text-sm">
            {error}
          </div>
        )}

        {/* Step 1: Connect email source */}
        {step === 1 && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Connect your email</h2>
            <p className="text-gray-500 text-sm mb-6">
              Connect the email account you want to summarize.
            </p>

            {outlookConnected ? (
              <div className="flex items-center gap-3 p-4 bg-green-50 rounded-lg border border-green-200">
                <span className="text-green-600 text-xl">✓</span>
                <span className="text-green-700 font-medium">Outlook connected!</span>
              </div>
            ) : (
              <div className="space-y-3">
                {providers?.sources.includes("outlook") && (
                  <button
                    onClick={connectOutlook}
                    className="w-full flex items-center gap-3 p-4 border-2 border-gray-200 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-colors text-left"
                  >
                    <span className="text-2xl">📧</span>
                    <div>
                      <div className="font-medium text-gray-900">Microsoft Outlook</div>
                      <div className="text-sm text-gray-500">Connect your Outlook / Office 365 inbox</div>
                    </div>
                  </button>
                )}
              </div>
            )}

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setStep(2)}
                disabled={!outlookConnected}
                className="bg-blue-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Connect destination */}
        {step === 2 && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Connect your destination</h2>
            <p className="text-gray-500 text-sm mb-6">
              Where should we send your digest?
            </p>

            {telegramLinked ? (
              <div className="flex items-center gap-3 p-4 bg-green-50 rounded-lg border border-green-200">
                <span className="text-green-600 text-xl">✓</span>
                <span className="text-green-700 font-medium">Telegram connected!</span>
              </div>
            ) : (
              <div className="space-y-4">
                {providers?.destinations.includes("telegram") && (
                  <div className="border-2 border-gray-200 rounded-xl p-4">
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-2xl">✈️</span>
                      <div>
                        <div className="font-medium text-gray-900">Telegram</div>
                        <div className="text-sm text-gray-500">Receive digests via Telegram bot</div>
                      </div>
                    </div>
                    {linkCode ? (
                      <div className="bg-blue-50 rounded-lg p-4 text-sm">
                        <p className="text-gray-700 mb-2">
                          Open Telegram and send this command to{" "}
                          <strong>{linkCode.bot_username}</strong>:
                        </p>
                        <code className="block bg-white border border-blue-200 rounded px-3 py-2 text-blue-800 font-mono text-base">
                          /start {linkCode.code}
                        </code>
                        <p className="text-gray-400 text-xs mt-2">
                          Waiting for confirmation… (checking every 3 seconds)
                        </p>
                      </div>
                    ) : (
                      <button
                        onClick={getTelegramCode}
                        className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg font-medium hover:bg-blue-700 transition-colors"
                      >
                        Generate link code
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="mt-6 flex justify-between">
              <button
                onClick={() => setStep(1)}
                className="text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg transition-colors"
              >
                Back
              </button>
              <button
                onClick={() => setStep(3)}
                disabled={!telegramLinked}
                className="bg-blue-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Continue
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Preferences */}
        {step === 3 && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Customize your digest</h2>
            <p className="text-gray-500 text-sm mb-6">
              Tell the AI how you want your emails summarized.
            </p>

            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Digest preferences
                </label>
                <textarea
                  value={digestPrefs}
                  onChange={(e) => setDigestPrefs(e.target.value)}
                  rows={5}
                  placeholder="Describe how you want your emails summarized…"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none text-sm"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  When should we send your digest?
                </label>
                <div className="grid grid-cols-3 gap-3">
                  {(["morning", "evening", "both"] as const).map((opt) => (
                    <button
                      key={opt}
                      onClick={() => setSchedule(opt)}
                      className={`py-2 px-3 rounded-lg border-2 text-sm font-medium capitalize transition-colors ${
                        schedule === opt
                          ? "border-blue-500 bg-blue-50 text-blue-700"
                          : "border-gray-200 text-gray-600 hover:border-gray-300"
                      }`}
                    >
                      {opt === "both" ? "Morning + Evening" : opt}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-between">
              <button
                onClick={() => setStep(2)}
                className="text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg transition-colors"
              >
                Back
              </button>
              <button
                onClick={savePreferences}
                disabled={saving}
                className="bg-blue-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {saving ? "Saving…" : "Finish setup"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function OnboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <div className="text-gray-500">Loading…</div>
        </div>
      }
    >
      <OnboardContent />
    </Suspense>
  );
}
