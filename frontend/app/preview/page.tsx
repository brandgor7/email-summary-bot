"use client";

import { signOut, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import type {
  DigestEmailItem,
  DigestResult,
  DigestSettings,
  DigestTodo,
  PreviewResponse,
  SourceToken,
  DestinationConfig,
} from "@/types";

const HAIKU_INPUT_COST_PER_TOKEN = 0.0000008;
const HAIKU_OUTPUT_COST_PER_TOKEN = 0.000004;
const MAX_CALLS_PER_HOUR = 10;

type SinceHours = 24 | 48 | 168;

const TIME_RANGE_LABELS: Record<SinceHours, string> = {
  24: "Last 24h",
  48: "Last 48h",
  168: "Last 7 days",
};

function estimateCost(inputTokens: number, outputTokens: number): string {
  const cost = inputTokens * HAIKU_INPUT_COST_PER_TOKEN + outputTokens * HAIKU_OUTPUT_COST_PER_TOKEN;
  return cost < 0.001 ? "<$0.001" : `$${cost.toFixed(4)}`;
}

function SectionBadge({ count, color }: { count: number; color: string }) {
  return (
    <span className={`ml-2 text-xs font-semibold px-2 py-0.5 rounded-full ${color}`}>
      {count}
    </span>
  );
}

function EmailCard({ item }: { item: DigestEmailItem }) {
  return (
    <div className="py-3 border-b border-gray-100 last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-medium text-gray-900 truncate">{item.subject}</div>
          <div className="text-xs text-gray-500 mt-0.5">{item.sender}</div>
        </div>
      </div>
      <div className="text-sm text-gray-700 mt-1">{item.summary}</div>
      {item.suggested_action && (
        <div className="text-xs text-blue-600 mt-1 font-medium">→ {item.suggested_action}</div>
      )}
    </div>
  );
}

function DigestSection({
  title,
  icon,
  items,
  badgeColor,
  open,
  onToggle,
}: {
  title: string;
  icon: string;
  items: DigestEmailItem[];
  badgeColor: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center">
          <span className="text-base mr-2">{icon}</span>
          <span className="font-semibold text-gray-900 text-sm">{title}</span>
          <SectionBadge count={items.length} color={badgeColor} />
        </div>
        <span className="text-gray-400 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && items.length > 0 && (
        <div className="px-5 pb-2">
          {items.map((item, i) => (
            <EmailCard key={i} item={item} />
          ))}
        </div>
      )}
      {open && items.length === 0 && (
        <div className="px-5 pb-4 text-sm text-gray-400">None</div>
      )}
    </div>
  );
}

function TodoList({ todos, open, onToggle }: { todos: DigestTodo[]; open: boolean; onToggle: () => void }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center">
          <span className="text-base mr-2">📋</span>
          <span className="font-semibold text-gray-900 text-sm">Todos</span>
          <SectionBadge count={todos.length} color="bg-purple-100 text-purple-700" />
        </div>
        <span className="text-gray-400 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && todos.length > 0 && (
        <ul className="px-5 pb-4 space-y-2">
          {todos.map((todo, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <span className="text-gray-400 mt-0.5">•</span>
              <div>
                <div className="text-gray-800">{todo.item}</div>
                <div className="text-xs text-gray-400">{todo.source_email}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {open && todos.length === 0 && (
        <div className="px-5 pb-4 text-sm text-gray-400">No action items</div>
      )}
    </div>
  );
}

function DigestView({ digest }: { digest: DigestResult }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(["urgent", "action_required", "fyi", "todos"])
  );

  function toggle(section: string) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  }

  return (
    <div className="space-y-3">
      <DigestSection
        title="Urgent"
        icon="🔴"
        items={digest.urgent}
        badgeColor="bg-red-100 text-red-700"
        open={openSections.has("urgent")}
        onToggle={() => toggle("urgent")}
      />
      <DigestSection
        title="Action Required"
        icon="🟡"
        items={digest.action_required}
        badgeColor="bg-yellow-100 text-yellow-700"
        open={openSections.has("action_required")}
        onToggle={() => toggle("action_required")}
      />
      <DigestSection
        title="FYI"
        icon="🔵"
        items={digest.fyi}
        badgeColor="bg-blue-100 text-blue-700"
        open={openSections.has("fyi")}
        onToggle={() => toggle("fyi")}
      />
      <TodoList
        todos={digest.todos}
        open={openSections.has("todos")}
        onToggle={() => toggle("todos")}
      />
    </div>
  );
}

export default function PreviewPage() {
  const { status } = useSession();
  const router = useRouter();

  const [sources, setSources] = useState<SourceToken[]>([]);
  const [destinations, setDestinations] = useState<DestinationConfig[]>([]);
  const [settings, setSettings] = useState<DigestSettings | null>(null);

  const [selectedSource, setSelectedSource] = useState<string>("");
  const [sinceHours, setSinceHours] = useState<SinceHours>(24);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [digestPrefs, setDigestPrefs] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [callsUsed, setCallsUsed] = useState(0);
  const [sending, setSending] = useState(false);

  const callsRef = useRef(callsUsed);
  callsRef.current = callsUsed;

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;
    Promise.all([
      api.get<SourceToken[]>("/users/me/sources"),
      api.get<DestinationConfig[]>("/users/me/destinations"),
      api.get<DigestSettings>("/users/me/settings"),
    ])
      .then(([srcRes, destRes, settingsRes]) => {
        setSources(srcRes.data);
        setDestinations(destRes.data);
        setSettings(settingsRes.data);
        setDigestPrefs(settingsRes.data.digest_prefs);
        if (srcRes.data.length > 0) {
          setSelectedSource(srcRes.data[0].provider);
        }
      })
      .catch(() => setError("Failed to load configuration."));
  }, [status]);

  async function runPreview(prefsOverride?: string) {
    if (!selectedSource) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<PreviewResponse>("/digest/preview", {
        source: selectedSource,
        since_hours: sinceHours,
        digest_prefs_override: prefsOverride ?? null,
      });
      setResult(res.data);
      setCallsUsed((n) => n + 1);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; headers?: Record<string, string>; data?: { detail?: string } } };
      if (axiosErr.response?.status === 429) {
        setError("Rate limit reached (10 previews/hour). Try again later.");
      } else if (axiosErr.response?.status === 404) {
        setError(axiosErr.response?.data?.detail ?? "Source provider not found.");
      } else {
        setError("Failed to run digest preview.");
      }
    } finally {
      setRunning(false);
    }
  }

  async function sendToDestination(destination: string) {
    if (!selectedSource || !result) return;
    setSending(true);
    setError(null);
    try {
      const res = await api.post<PreviewResponse>("/digest/preview", {
        source: selectedSource,
        since_hours: sinceHours,
        digest_prefs_override: digestPrefs !== settings?.digest_prefs ? digestPrefs : null,
        send_to: destination,
      });
      setResult(res.data);
      setCallsUsed((n) => n + 1);
    } catch {
      setError(`Failed to send to ${destination}.`);
    } finally {
      setSending(false);
    }
  }

  async function savePrefs() {
    setSaving(true);
    setSaveSuccess(false);
    setError(null);
    try {
      const res = await api.put<DigestSettings>("/users/me/settings", {
        digest_prefs: digestPrefs,
        schedule: settings?.schedule ?? "morning",
        enabled: settings?.enabled ?? true,
      });
      setSettings(res.data);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      setError("Failed to save preferences.");
    } finally {
      setSaving(false);
    }
  }

  const callsRemaining = MAX_CALLS_PER_HOUR - callsUsed;
  const nearLimit = callsRemaining <= 3;

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-lg font-semibold text-gray-900">
            <span>📬</span> Email Digest
          </div>
          <div className="flex items-center gap-4">
            <a href="/settings" className="text-sm text-blue-600 hover:text-blue-700 font-medium">
              Settings
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

      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Digest Preview</h1>
          <p className="text-sm text-gray-500 mt-1">
            Run your digest on demand, tune the prompt, and see results instantly.
          </p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {sources.length === 0 ? (
          <div className="bg-white rounded-2xl border border-gray-200 p-8 text-center">
            <div className="text-3xl mb-3">📭</div>
            <h2 className="text-base font-semibold text-gray-900 mb-1">No email source connected</h2>
            <p className="text-sm text-gray-500 mb-4">
              Connect an email account to start previewing your digest.
            </p>
            <a
              href="/onboard"
              className="inline-block bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              Connect email
            </a>
          </div>
        ) : (
          <>
            {/* Controls */}
            <div className="bg-white rounded-2xl border border-gray-200 p-5">
              <div className="flex flex-wrap items-end gap-4">
                <div className="flex-1 min-w-40">
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">Source</label>
                  <select
                    value={selectedSource}
                    onChange={(e) => setSelectedSource(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {sources.map((s) => (
                      <option key={s.provider} value={s.provider}>
                        {s.provider.charAt(0).toUpperCase() + s.provider.slice(1)} — {s.provider_email}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">Time range</label>
                  <div className="flex gap-1.5">
                    {([24, 48, 168] as SinceHours[]).map((h) => (
                      <button
                        key={h}
                        onClick={() => setSinceHours(h)}
                        className={`px-3 py-2 rounded-lg text-xs font-medium border transition-colors ${
                          sinceHours === h
                            ? "border-blue-500 bg-blue-50 text-blue-700"
                            : "border-gray-200 text-gray-600 hover:border-gray-300"
                        }`}
                      >
                        {TIME_RANGE_LABELS[h]}
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  onClick={() => runPreview()}
                  disabled={running || !selectedSource}
                  className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors whitespace-nowrap"
                >
                  {running ? "Running…" : "Run digest now"}
                </button>
              </div>

              {nearLimit && (
                <div className="mt-3 text-xs text-amber-600 font-medium">
                  {callsRemaining} preview{callsRemaining !== 1 ? "s" : ""} remaining this hour
                </div>
              )}
            </div>

            {/* Loading state */}
            {running && (
              <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
                <div className="flex items-center justify-center gap-3 text-gray-500">
                  <svg className="animate-spin h-5 w-5 text-blue-500" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  <span className="text-sm">Summarizing your emails… (5–15s)</span>
                </div>
              </div>
            )}

            {/* Digest result */}
            {result && !running && (
              <div className="space-y-4">
                <DigestView digest={result.digest} />

                {/* Token usage + cost + send */}
                <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs text-gray-500 space-y-0.5">
                    <div>
                      <span className="font-medium text-gray-700">{result.token_usage.input_tokens.toLocaleString()}</span> input /{" "}
                      <span className="font-medium text-gray-700">{result.token_usage.output_tokens.toLocaleString()}</span> output tokens
                    </div>
                    <div>
                      Estimated cost:{" "}
                      <span className="font-medium text-gray-700">
                        {estimateCost(result.token_usage.input_tokens, result.token_usage.output_tokens)}
                      </span>
                    </div>
                    {result.send_result && (
                      <div className={result.send_result.status === "sent" ? "text-green-600" : "text-red-600"}>
                        {result.send_result.status === "sent"
                          ? `✓ Sent to ${result.send_result.destination}`
                          : `Send failed: ${result.send_result.error ?? "unknown error"}`}
                      </div>
                    )}
                  </div>

                  {destinations.length > 0 && (
                    <div className="flex gap-2 flex-wrap">
                      {destinations.map((d) => (
                        <button
                          key={d.provider}
                          onClick={() => sendToDestination(d.provider)}
                          disabled={sending}
                          className="text-xs font-medium px-4 py-2 rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-50 transition-colors"
                        >
                          {sending ? "Sending…" : `Send to ${d.provider.charAt(0).toUpperCase() + d.provider.slice(1)}`}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Prompt editor */}
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-900 mb-1">Prompt editor</h2>
              <p className="text-xs text-gray-500 mb-4">
                Edit your digest preferences and re-run to see how the output changes.
              </p>
              <textarea
                value={digestPrefs}
                onChange={(e) => setDigestPrefs(e.target.value)}
                rows={5}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none text-sm"
              />
              <div className="mt-3 flex items-center justify-between flex-wrap gap-2">
                <div className="flex gap-2">
                  <button
                    onClick={() => runPreview(digestPrefs)}
                    disabled={running || !selectedSource}
                    className="text-sm font-medium px-4 py-2 rounded-lg border border-blue-500 text-blue-600 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                  >
                    Re-run with this prompt
                  </button>
                  <button
                    onClick={savePrefs}
                    disabled={saving}
                    className="text-sm font-medium px-4 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  >
                    {saving ? "Saving…" : "Save as default"}
                  </button>
                </div>
                {saveSuccess && (
                  <span className="text-xs text-green-600 font-medium">✓ Saved as default</span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
