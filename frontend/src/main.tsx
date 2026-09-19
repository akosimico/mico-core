import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bell,
  Brain,
  CheckCircle2,
  Clock,
  Inbox,
  ListChecks,
  RefreshCw,
  Server,
  type LucideIcon,
  User,
  Zap,
} from "lucide-react";
import "./styles.css";

type Dashboard = {
  task_counts: Record<string, number>;
  reminders_due: number;
  automations_enabled: number;
  memory_count: number;
  monitors: { id: number; name: string; url: string; status: string; error?: string }[];
  recent_activity: { action: string; status: string; created_at: string }[];
};

// The dashboard is served by the same nginx container that proxies /api to
// FastAPI. Resolving from the browser's current origin avoids a stale or
// externally supplied VITE_API_URL pointing at an unreachable localhost.
const API = `${window.location.origin}/api`;
const DASHBOARD_REFRESH_MS = 5_000;

function App() {
  const [userId, setUserId] = useState(localStorage.getItem("mico-user-id") ?? "");
  const [activeUserId, setActiveUserId] = useState(localStorage.getItem("mico-user-id") ?? "");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async (id = activeUserId, background = false) => {
    id = id.trim();
    if (!id) return;
    if (!background) setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/dashboard/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error();
      setData(await response.json());
      setLastUpdated(new Date());
    } catch (error) {
      if (!background) setData(null);
      setError(
        `Couldn't reach ${API}. ${
          error instanceof Error ? error.message : "Check that the backend container is running, then retry."
        }`
      );
    } finally {
      if (!background) setLoading(false);
    }
  }, [activeUserId]);

  useEffect(() => {
    if (!activeUserId.trim()) return;
    void load(activeUserId);
    const timer = window.setInterval(() => void load(activeUserId, true), DASHBOARD_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [activeUserId, load]);

  const cards = data
    ? [
        {
          icon: ListChecks,
          label: "Active tasks",
          value: (data.task_counts.pending ?? 0) + (data.task_counts.in_progress ?? 0),
          detail: "Tasks still in motion",
        },
        { icon: Bell, label: "Reminders", value: data.reminders_due, detail: "Waiting to be completed" },
        { icon: Zap, label: "Automations", value: data.automations_enabled, detail: "Schedules enabled" },
        { icon: Brain, label: "Memories", value: data.memory_count, detail: "Saved context" },
        { icon: Server, label: "Services", value: data.monitors.length, detail: "Monitored endpoints" },
      ]
    : [];

  const healthyCount = data ? data.monitors.filter((m) => m.status === "healthy").length : 0;

  return (
    <main className="app-shell">
      <div className="glow glow-a" aria-hidden="true" />
      <div className="glow glow-b" aria-hidden="true" />

      <section className="dashboard-shell">
        <header className="hero">
          <div className="hero-copy">
            <p className="eyebrow">
              <Activity size={13} strokeWidth={2.5} />
              Mico-core
            </p>
            <h1>Command center</h1>
            <p className="subtitle">A focused view of your Discord assistant's work.</p>
          </div>

          <form
            className="user-form"
            onSubmit={(event) => {
              event.preventDefault();
              const id = userId.trim();
              localStorage.setItem("mico-user-id", id);
              setActiveUserId(id);
              void load(id);
            }}
          >
            <label htmlFor="user-id">Discord user ID</label>
            <div className="input-row">
              <div className="input-wrap">
                <User size={16} strokeWidth={2} />
                <input
                  id="user-id"
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                  placeholder="Paste your Discord user ID"
                  autoComplete="off"
                />
              </div>
              <button disabled={loading || !userId.trim()}>
                {loading ? (
                  <>
                    <RefreshCw size={16} className="spin" /> Loading
                  </>
                ) : (
                  <>
                    Load workspace <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </form>
        </header>

        <div className="info-strip">
          <div className="info-strip-text">
            <strong>How it works</strong>
            <p>{lastUpdated ? `Live updates every 5 seconds · Last synced ${lastUpdated.toLocaleTimeString()}` : "Use the same Discord user ID that sends MICO commands."}</p>
          </div>
          {data && (
            <button className="ghost-button" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={14} className={loading ? "spin" : ""} />
              Refresh data
            </button>
          )}
        </div>

        {error && (
          <section className="error-panel">
            <AlertTriangle size={20} strokeWidth={2} />
            <div>
              <strong>Dashboard unavailable</strong>
              <p>{error}</p>
            </div>
            <button onClick={() => void load()} disabled={loading}>
              Try again
            </button>
          </section>
        )}

        {!data && !error && (
          <section className="empty-state">
            <div className="empty-icon">
              <Inbox size={28} strokeWidth={1.75} />
            </div>
            <h2>Load your workspace</h2>
            <p>Paste your Discord user ID above to see tasks, reminders, automations, monitors, and PC-agent activity.</p>
          </section>
        )}

        {data && (
          <>
            <section className="metric-grid">
              {cards.map(({ icon: Icon, label, value, detail }, index) => (
                <article
                  key={label}
                  className="metric-card"
                  style={{ animationDelay: `${index * 60}ms` }}
                >
                  <div className="metric-icon">
                    <Icon size={18} strokeWidth={2} />
                  </div>
                  <p>{label}</p>
                  <strong>{value}</strong>
                  <span>{detail}</span>
                </article>
              ))}
            </section>

            <section className="content-grid">
              <Panel
                title="Service health"
                label="Live status"
                count={`${healthyCount}/${data.monitors.length} healthy`}
                icon={Server}
              >
                {data.monitors.length ? (
                  data.monitors.map((m, index) => (
                    <div
                      key={m.id}
                      className="list-row"
                      style={{ animationDelay: `${index * 45}ms` }}
                    >
                      <span className={`status-dot ${m.status === "healthy" ? "healthy" : "attention"}`} />
                      <div className="list-row-text">
                        <b>{m.name}</b>
                        <p>{m.url}</p>
                        {m.error && <small>{m.error}</small>}
                      </div>
                      {m.status === "healthy" ? (
                        <em className="tag healthy">
                          <CheckCircle2 size={13} /> {m.status}
                        </em>
                      ) : (
                        <em className="tag attention">
                          <AlertTriangle size={13} /> {m.status}
                        </em>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="panel-empty">
                    No services are monitored yet. Use <code>!monitor add</code> in Discord to add one.
                  </p>
                )}
              </Panel>

              <Panel
                title="Recent PC activity"
                label="Secure actions"
                count={`${data.recent_activity.length} events`}
                icon={Clock}
              >
                {data.recent_activity.length ? (
                  data.recent_activity.map((a, index) => (
                    <div
                      key={index}
                      className="list-row"
                      style={{ animationDelay: `${index * 45}ms` }}
                    >
                      <span className={`status-dot ${a.status === "SUCCESS" ? "healthy" : "attention"}`} />
                      <div className="list-row-text">
                        <b>{a.action.replace(/_/g, " ")}</b>
                        <p>{new Date(a.created_at).toLocaleString()}</p>
                      </div>
                      {a.status === "SUCCESS" ? (
                        <em className="tag healthy">
                          <CheckCircle2 size={13} /> {a.status}
                        </em>
                      ) : (
                        <em className="tag attention">
                          <AlertTriangle size={13} /> {a.status}
                        </em>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="panel-empty">No audited PC-agent actions for this user.</p>
                )}
              </Panel>
            </section>
          </>
        )}
      </section>
    </main>
  );
}

function Panel({
  title,
  label,
  count,
  icon: Icon,
  children,
}: {
  title: string;
  label: string;
  count: string;
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <article className="panel">
      <header>
        <div className="panel-title">
          <div className="panel-icon">
            <Icon size={16} strokeWidth={2} />
          </div>
          <div>
            <p className="eyebrow">{label}</p>
            <h2>{title}</h2>
          </div>
        </div>
        <span className="panel-count">{count}</span>
      </header>
      <div className="panel-body">{children}</div>
    </article>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
