import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  TASK_CATEGORIES, TASK_STATUSES, TASK_PRIORITIES,
  findCategory, findStatus, findPriority, isOverdue, fmtDueDate,
} from "@/lib/tasks";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Plus, Filter, AlertTriangle, X, Search, Clock } from "lucide-react";
import { toast } from "sonner";
import TaskDrawer from "@/components/tasks/TaskDrawer";
import TaskCreateModal from "@/components/tasks/TaskCreateModal";

const STATUS_TABS = [
  { key: "", label: "All" },
  ...TASK_STATUSES.map((s) => ({ key: s.key, label: s.label })),
];

export default function Tasks() {
  const { user } = useAuth();
  const isManagerPlus = user?.role === "admin" || user?.role === "manager";
  const [searchParams, setSearchParams] = useSearchParams();

  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  const [filters, setFilters] = useState(() => ({
    status: searchParams.get("status") || "",
    category: searchParams.get("category") || "",
    priority: searchParams.get("priority") || "",
    property_id: searchParams.get("property_id") || "",
    assignee_id: searchParams.get("assignee_id") || "",
    mine: searchParams.get("mine") === "1",
    overdue: searchParams.get("overdue") === "1",
    q: "",
  }));
  const [properties, setProperties] = useState([]);
  const [users, setUsers] = useState([]);
  const [creating, setCreating] = useState(false);
  const [activeId, setActiveId] = useState(null);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    Promise.all([
      api.get("/properties"),
      api.get("/users/assignable"),
    ]).then(([p, u]) => {
      setProperties(p.data.items || []);
      setUsers(u.data.items || []);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = {};
    if (filters.status) params.status = filters.status;
    if (filters.category) params.category = filters.category;
    if (filters.priority) params.priority = filters.priority;
    if (filters.property_id) params.property_id = filters.property_id;
    if (filters.assignee_id) params.assignee_id = filters.assignee_id;
    if (filters.mine) params.mine = true;
    Promise.all([
      api.get("/tasks", { params }),
      api.get("/tasks/stats"),
    ]).then(([r, s]) => {
      if (cancelled) return;
      setItems(r.data.items || []);
      setStats(s.data || null);
      setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [version, filters.status, filters.category, filters.priority, filters.property_id, filters.assignee_id, filters.mine]);

  const filtered = useMemo(() => {
    let list = items;
    if (filters.overdue) {
      const today = new Date().toISOString().slice(0, 10);
      list = list.filter((t) => t.due_date && t.due_date < today && t.status !== "done");
    }
    if (!filters.q.trim()) return list;
    const q = filters.q.toLowerCase();
    return list.filter((t) =>
      (t.title || "").toLowerCase().includes(q) ||
      (t.description || "").toLowerCase().includes(q) ||
      (t.property_name || "").toLowerCase().includes(q) ||
      (t.assignee_name || "").toLowerCase().includes(q)
    );
  }, [items, filters.q, filters.overdue]);

  const clearFilters = () => {
    setFilters({ status: "", category: "", priority: "", property_id: "", assignee_id: "", mine: false, overdue: false, q: "" });
    setSearchParams({});
  };

  const onCreated = (t) => {
    setCreating(false);
    toast.success("Task created");
    refresh();
    setActiveId(t.id);
  };

  return (
    <div className="space-y-8" data-testid="tasks-page">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Operations</div>
          <h1 className="font-display text-3xl tracking-tight mt-1">Tasks</h1>
          <p className="text-sm text-dim mt-2 max-w-2xl">
            Track maintenance, housekeeping, compliance, restocks, inspections and guest issues across every property.
          </p>
        </div>
        {isManagerPlus && (
          <button
            data-testid="new-task-button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 bg-brand text-black text-sm font-medium px-4 py-2 rounded-md hover:opacity-90 h-fit"
          >
            <Plus className="w-4 h-4" /> New task
          </button>
        )}
      </header>

      {/* Stat strip */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-3" data-testid="task-stat-strip">
          <StatTile testid="stat-total"  label="Total"        value={stats.total} />
          <StatTile testid="stat-open"   label="Open"         value={stats.by_status.open} />
          <StatTile testid="stat-progress" label="In progress" value={stats.by_status.in_progress} />
          <StatTile testid="stat-blocked" label="Blocked"      value={stats.by_status.blocked} accent="#E05A50" />
          <StatTile testid="stat-overdue" label="Overdue"      value={stats.overdue} accent="#E05A50" icon={<AlertTriangle className="w-3.5 h-3.5" />} />
          <StatTile testid="stat-mine"   label="My open"      value={stats.mine_open} accent="#D9A05B" />
        </div>
      )}

      {/* Status tabs */}
      <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-1" data-testid="status-tabs">
        {STATUS_TABS.map((t) => (
          <button
            key={t.key || "all"}
            onClick={() => setFilters({ ...filters, status: t.key })}
            data-testid={`status-tab-${t.key || "all"}`}
            className={`px-3 py-1.5 text-xs rounded-full whitespace-nowrap border transition-colors ${
              filters.status === t.key
                ? "bg-[#1A1D24] text-white border-[#22252F]"
                : "text-[#8F95A3] border-transparent hover:text-white hover:bg-[#14161D]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="surface rounded-md p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3" data-testid="task-filters">
        <div className="lg:col-span-2 relative">
          <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-dim pointer-events-none" />
          <Input
            placeholder="Search title, property, assignee…"
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            data-testid="filter-search"
            className="pl-8 bg-transparent border-[#22252F] text-sm"
          />
        </div>
        <FilterSelect
          testid="filter-category" placeholder="Category" value={filters.category}
          onChange={(v) => setFilters({ ...filters, category: v })}
          options={TASK_CATEGORIES.map((c) => ({ value: c.key, label: c.label }))}
        />
        <FilterSelect
          testid="filter-priority" placeholder="Priority" value={filters.priority}
          onChange={(v) => setFilters({ ...filters, priority: v })}
          options={TASK_PRIORITIES.map((p) => ({ value: p.key, label: p.label }))}
        />
        <FilterSelect
          testid="filter-property" placeholder="Property" value={filters.property_id}
          onChange={(v) => setFilters({ ...filters, property_id: v })}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <FilterSelect
          testid="filter-assignee" placeholder="Assignee" value={filters.assignee_id}
          onChange={(v) => setFilters({ ...filters, assignee_id: v })}
          options={users.map((u) => ({ value: u.id, label: u.name || u.email }))}
        />
      </div>

      <div className="flex items-center gap-3 text-xs">
        <button
          onClick={() => setFilters({ ...filters, mine: !filters.mine })}
          data-testid="filter-mine"
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border transition-colors ${
            filters.mine
              ? "bg-[#D9A05B]/15 text-[#D9A05B] border-[#D9A05B]/50"
              : "text-dim border-[#22252F] hover:text-white"
          }`}
        >
          Only mine
        </button>
        <button
          onClick={clearFilters}
          data-testid="filter-clear"
          className="inline-flex items-center gap-1 text-dim hover:text-white"
        >
          <X className="w-3 h-3" /> Clear filters
        </button>
        <span className="ml-auto text-dim">{filtered.length} task{filtered.length === 1 ? "" : "s"}</span>
      </div>

      {/* Table */}
      <div className="surface rounded-md overflow-hidden">
        {loading ? (
          <div className="p-8 text-dim text-sm">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-dim text-sm" data-testid="tasks-empty">
            <Filter className="w-5 h-5 mx-auto mb-2 opacity-50" />
            No tasks match these filters yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-[#0E1015]">
              <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
                <th className="text-left px-4 py-3 font-semibold">Title</th>
                <th className="text-left px-4 py-3 font-semibold">Category</th>
                <th className="text-left px-4 py-3 font-semibold">Property</th>
                <th className="text-left px-4 py-3 font-semibold">Assignee</th>
                <th className="text-center px-4 py-3 font-semibold">Priority</th>
                <th className="text-center px-4 py-3 font-semibold">Status</th>
                <th className="text-left px-4 py-3 font-semibold">Due</th>
              </tr>
            </thead>
            <tbody data-testid="tasks-table-body">
              {filtered.map((t) => {
                const cat = findCategory(t.category);
                const st = findStatus(t.status);
                const pr = findPriority(t.priority);
                const overdue = isOverdue(t);
                return (
                  <tr
                    key={t.id}
                    data-testid={`task-row-${t.id}`}
                    onClick={() => setActiveId(t.id)}
                    className="tbl-row cursor-pointer hover:bg-[#14161D]"
                  >
                    <td className="px-4 py-3">
                      <div className="text-white">{t.title}</div>
                      {t.description && (
                        <div className="text-[11px] text-dim mt-0.5 truncate max-w-[28ch]">{t.description}</div>
                      )}
                      <div className="text-[10px] text-dim mt-1 flex items-center gap-2">
                        {t.checklist?.length > 0 && (
                          <span>{t.checklist.filter((c) => c.done).length}/{t.checklist.length} ☑</span>
                        )}
                        {t.photo_count > 0 && <span>📷 {t.photo_count}</span>}
                        {t.comments?.length > 0 && <span>💬 {t.comments.length}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[11px] inline-flex items-center gap-1.5 px-2 py-0.5 rounded border" style={{ color: cat.color, borderColor: cat.color + "55" }}>
                        {cat.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-dim">{t.property_name || "—"}</td>
                    <td className="px-4 py-3 text-dim">{t.assignee_name || "—"}</td>
                    <td className="px-4 py-3 text-center">
                      <span className="text-[11px]" style={{ color: pr.color }}>{pr.label}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="text-[11px] inline-block px-2 py-0.5 rounded-full border" style={{ color: st.color, borderColor: st.color + "55" }}>
                        {st.label}
                      </span>
                    </td>
                    <td className={`px-4 py-3 text-xs tabular-nums ${overdue ? "text-[#E05A50]" : "text-dim"}`}>
                      <span className="inline-flex items-center gap-1">
                        {overdue && <AlertTriangle className="w-3 h-3" />}
                        <Clock className="w-3 h-3 opacity-50" />
                        {fmtDueDate(t.due_date)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {creating && (
        <TaskCreateModal
          properties={properties}
          users={users}
          onClose={() => setCreating(false)}
          onCreated={onCreated}
        />
      )}

      {activeId && (
        <TaskDrawer
          taskId={activeId}
          onClose={() => setActiveId(null)}
          onChanged={refresh}
          properties={properties}
          users={users}
        />
      )}
    </div>
  );
}

function StatTile({ label, value, accent, icon, testid }) {
  return (
    <div className="surface rounded-md p-3" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.18em] text-dim flex items-center gap-1">
        {icon} {label}
      </div>
      <div className="font-display text-2xl mt-1 tabular-nums" style={accent ? { color: accent } : {}}>
        {value ?? 0}
      </div>
    </div>
  );
}

function FilterSelect({ testid, value, onChange, options, placeholder }) {
  return (
    <Select value={value || "__all__"} onValueChange={(v) => onChange(v === "__all__" ? "" : v)}>
      <SelectTrigger data-testid={testid} className="bg-transparent border-[#22252F] text-sm">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="bg-[#12141A] border-[#22252F] text-white max-h-72">
        <SelectItem value="__all__">All {placeholder.toLowerCase()}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
