"use client";

import { signOut, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import api from "@/lib/api";
import type { DigestSettings } from "@/types";

interface ConnectedSource {
  provider: string;
  provider_email: string;
}

interface ConnectedDestination {
  provider: string;
}

export default function SettingsPage() {
  const { status } = useSession();
  const router = useRouter();

  const [settings, setSettings] = useState<DigestSettings | null>(null);
  const [sources, setSources] = useState<ConnectedSource[]>([]);
  const [destinations, setDestinations] = useState<ConnectedDestination[]>([]);
  const [digestPrefs, setDigestPrefs] = useState("");
  const [schedule, setSchedule] = useState<"morning" | "evening" | "both">("morning");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;
    loadData();
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadData() {
    setError(null);
    try {
      const [settingsRes, sourcesRes, destsRes] = await Promise.all([
        api.get<DigestSettings>("/users/me/settings"),
        api.get<ConnectedSource[]>("/users/me/sources"),
        api.get<ConnectedDestination[]>("/users/me/destinations"),
      ]);
      setSettings(settingsRes.data);
      setDigestPrefs(settingsRes.data.digest_prefs);
      setSchedule(settingsRes.data.schedule);
      setEnabled(settingsRes.data.enabled);
      setSources(sourcesRes.data);
      setDestinations(destsRes.data);
    } catch {
      // Sources/destinations endpoints may not exist yet; settings is required
      try {
        const settingsRes = await api.get<DigestSettings>("/users/me/settings");
        setSettings(settingsRes.data);
        setDigestPrefs(settingsRes.data.digest_prefs);
        setSchedule(settingsRes.data.schedule);
        setEnabled(settingsRes.data.enabled);
      } catch {
        setError("Failed to load settings.");
      }
    }
  }

  async function saveSettings() {
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    try {
      const res = await api.put<DigestSettings>("/users/me/settings", {
        digest_prefs: digestPrefs,
        schedule,
        enabled,
      });
      setSettings(res.data);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      setError("Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  async function disconnectSource(provider: string) {
    if (!confirm(`Disconnect ${provider}? You will stop receiving digests from this account.`)) return;
    try {
      await api.delete(`/users/me/sources/${provider}`);
      setSources((prev) => prev.filter((s) => s.provider !== provider));
    } catch {
      setError(`Failed to disconnect ${provider}.`);
    }
  }

  async function disconnectDestination(provider: string) {
    if (!confirm(`Disconnect ${provider}? You will no longer receive digests here.`)) return;
    try {
      await api.delete(`/users/me/destinations/${provider}`);
      setDestinations((prev) => prev.filter((d) => d.provider !== provider));
    } catch {
      setError(`Failed to disconnect ${provider}.`);
    }
  }

  if (status === "loading" || !settings) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-lg font-semibold text-gray-900">
            <span>📬</span> Email Digest
          </div>
          <div className="flex items-center gap-3">
            <a
              href="/onboard"
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              Add connection
            </a>
            <button
              onClick={() => signOut({ callbackUrl: "/" })}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {/* Connected sources */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-900">Connected email sources</h2>
            <a href="/onboard" className="text-sm text-blue-600 hover:text-blue-700">
              + Add
            </a>
          </div>
          {sources.length === 0 ? (
            <div className="text-sm text-gray-400 py-2">
              No email source connected.{" "}
              <a href="/onboard" className="text-blue-600 hover:underline">
                Connect one
              </a>{" "}
              to start receiving digests.
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {sources.map((s) => (
                <li key={s.provider} className="py-3 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-gray-900 capitalize">{s.provider}</div>
                    <div className="text-xs text-gray-500">{s.provider_email}</div>
                  </div>
                  <button
                    onClick={() => disconnectSource(s.provider)}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Disconnect
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Connected destinations */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-900">Connected destinations</h2>
            <a href="/onboard" className="text-sm text-blue-600 hover:text-blue-700">
              + Add
            </a>
          </div>
          {destinations.length === 0 ? (
            <div className="text-sm text-gray-400 py-2">
              No destination connected.{" "}
              <a href="/onboard" className="text-blue-600 hover:underline">
                Connect Telegram
              </a>{" "}
              to receive your digests.
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {destinations.map((d) => (
                <li key={d.provider} className="py-3 flex items-center justify-between">
                  <div className="text-sm font-medium text-gray-900 capitalize">{d.provider}</div>
                  <button
                    onClick={() => disconnectDestination(d.provider)}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Disconnect
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Digest settings */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-5">Digest preferences</h2>
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                How should the AI summarize your emails?
              </label>
              <textarea
                value={digestPrefs}
                onChange={(e) => setDigestPrefs(e.target.value)}
                rows={5}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Schedule</label>
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

            <div className="flex items-center justify-between py-1">
              <div>
                <div className="text-sm font-medium text-gray-900">Scheduled digests</div>
                <div className="text-xs text-gray-500">
                  {enabled ? "Enabled — digests run on your schedule" : "Paused — no digests until re-enabled"}
                </div>
              </div>
              <button
                onClick={() => setEnabled(!enabled)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  enabled ? "bg-blue-600" : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                    enabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between pt-2">
              {saveSuccess && (
                <span className="text-sm text-green-600 font-medium">✓ Saved</span>
              )}
              {!saveSuccess && <span />}
              <button
                onClick={saveSettings}
                disabled={saving}
                className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {saving ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
