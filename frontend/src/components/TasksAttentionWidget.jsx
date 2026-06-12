import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { AlertTriangle, UserCheck, Ban, ArrowRight } from "lucide-react";

// Three-card "Tasks needing attention" widget for the Analytics Dashboard.
// Each card links to /tasks with the relevant filter pre-applied.
export default function TasksAttentionWidget() {
  const { user } = useAuth();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.get("/tasks/stats")
      .then((r) => { if (!cancelled) { setStats(r.data); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (!user) return null;

  const cards = [
    {
      key: "overdue",
      label: "Overdue tasks",
      value: stats?.overdue ?? 0,
      accent: "#E05A50",
      icon: AlertTriangle,
      to: "/tasks?overdue=1",
      testid: "widget-overdue",
    },
    {
      key: "mine",
      label: "My open tasks",
      value: stats?.mine_open ?? 0,
      accent: "#D9A05B",
      icon: UserCheck,
      to: "/tasks?mine=1",
      testid: "widget-mine-open",
    },
    {
      key: "blocked",
      label: "Blocked tasks",
      value: stats?.by_status?.blocked ?? 0,
      accent: "#7AB8FF",
      icon: Ban,
      to: "/tasks?status=blocked",
      testid: "widget-blocked",
    },
  ];

  return (
    <section data-testid="tasks-attention-widget" className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Tasks needing attention</div>
        <Link
          to="/tasks"
          data-testid="widget-go-tasks"
          className="text-[11px] text-dim hover:text-white inline-flex items-center gap-1"
        >
          Open task board <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {cards.map(({ key, label, value, accent, icon: Icon, to, testid }) => (
          <Link
            key={key}
            to={to}
            data-testid={testid}
            className="surface rounded-md p-5 group hover:border-[#3A3F4C] transition-colors"
            style={{ borderColor: value > 0 ? accent + "55" : "" }}
          >
            <div className="flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-[0.18em] text-dim">{label}</div>
              <Icon className="w-3.5 h-3.5 opacity-60" style={{ color: accent }} />
            </div>
            <div className="font-display text-3xl font-light tracking-tighter mt-2 tabular-nums" style={value > 0 ? { color: accent } : { color: "#F2F3F5" }}>
              {loading ? "…" : value}
            </div>
            <div className="text-[11px] text-dim mt-2 inline-flex items-center gap-1 group-hover:text-white">
              View list <ArrowRight className="w-3 h-3" />
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
