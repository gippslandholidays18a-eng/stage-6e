import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  REVIEW_SOURCES, SENTIMENTS, findSentiment, fmtReviewDate,
} from "@/lib/reviews";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Plus, Star, Flag, AlertTriangle, Search, X, Pencil, Trash2, MessageSquare,
} from "lucide-react";
import { toast } from "sonner";
import ReviewFormModal from "@/components/reviews/ReviewFormModal";

export default function Reviews() {
  const { user } = useAuth();
  const isMgr = user?.role === "admin" || user?.role === "manager";
  const [items, setItems] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const [filters, setFilters] = useState({
    source_platform: "", sentiment: "", property_id: "",
    priority_only: false, responded: "", q: "",
  });
  const [editing, setEditing] = useState(null);   // review being edited
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    api.get("/properties").then((r) => setProperties(r.data.items || [])).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = {};
    if (filters.source_platform) params.source_platform = filters.source_platform;
    if (filters.sentiment) params.sentiment = filters.sentiment;
    if (filters.property_id) params.property_id = filters.property_id;
    if (filters.priority_only) params.priority_only = true;
    if (filters.responded) params.responded = filters.responded;
    if (filters.q.trim()) params.q = filters.q.trim();
    Promise.all([
      api.get("/reviews", { params }),
      isMgr ? api.get("/reviews/analytics") : Promise.resolve({ data: null }),
    ]).then(([r, a]) => {
      if (cancelled) return;
      setItems(r.data.items || []);
      setAnalytics(a.data || null);
      setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [version, filters.source_platform, filters.sentiment, filters.property_id,
      filters.priority_only, filters.responded, filters.q, isMgr]);

  const remove = async (r) => {
    if (!window.confirm(`Delete review by ${r.guest_name}?`)) return;
    try {
      await api.delete(`/reviews/${r.id}`);
      toast.success("Deleted");
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const onSaved = (doc, wasCreate) => {
    setCreating(false);
    setEditing(null);
    refresh();
    if (wasCreate) {
      toast.success("Review saved · add another?", {
        action: { label: "Add another", onClick: () => setCreating(true) },
      });
    } else {
      toast.success("Review updated");
    }
  };

  const clearFilters = () => setFilters({
    source_platform: "", sentiment: "", property_id: "",
    priority_only: false, responded: "", q: "",
  });

  return (
    <div className="space-y-8" data-testid="reviews-page">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Reputation</div>
          <h1 className="font-display text-3xl tracking-tight mt-1">Guest reviews</h1>
          <p className="text-sm text-dim mt-2 max-w-2xl">
            Track and respond to guest reviews from every OTA and direct channel.
            Reviews rated 3★ or below and unresponded are flagged as priority automatically.
          </p>
        </div>
        {isMgr && (
          <button
            data-testid="new-review-button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 bg-brand text-black text-sm font-medium px-4 py-2 rounded-md hover:opacity-90 h-fit"
          >
            <Plus className="w-4 h-4" /> New review
          </button>
        )}
      </header>

      {analytics && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="reviews-kpis">
          <KPI testid="kpi-total" label="Total reviews" value={analytics.total} />
          <KPI testid="kpi-avg" label="Average rating" value={analytics.avg_rating != null ? `${analytics.avg_rating} / 5` : "—"} accent="#D9A05B" />
          <KPI testid="kpi-response" label="Response rate" value={analytics.response_rate != null ? `${analytics.response_rate}%` : "—"} accent="#5BD1A8" />
          <KPI testid="kpi-priority" label="Priority open" value={analytics.priority_open} accent="#E05A50" icon={<AlertTriangle className="w-3.5 h-3.5" />} />
        </div>
      )}

      {analytics && (analytics.by_property?.length > 0 || analytics.by_source?.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <AnalyticsPanel testid="analytics-by-property" title="By property" rows={analytics.by_property.slice(0, 8)}
            columns={[
              { key: "property_name", label: "Property", align: "left" },
              { key: "total", label: "Reviews", align: "right" },
              { key: "avg_rating", label: "Avg", align: "right", fmt: (v) => v == null ? "—" : v },
              { key: "priority_open", label: "Priority", align: "right", accent: "#E05A50" },
            ]} />
          <AnalyticsPanel testid="analytics-by-source" title="By source" rows={analytics.by_source.slice(0, 8)}
            columns={[
              { key: "source_platform", label: "Source", align: "left" },
              { key: "total", label: "Reviews", align: "right" },
              { key: "avg_rating", label: "Avg", align: "right", fmt: (v) => v == null ? "—" : v },
              { key: "response_rate", label: "Resp %", align: "right", fmt: (v) => `${v}%` },
            ]} />
        </div>
      )}

      {/* Filters */}
      <div className="surface rounded-md p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3" data-testid="review-filters">
        <div className="lg:col-span-2 relative">
          <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-dim pointer-events-none" />
          <Input
            placeholder="Search guest, text, property…"
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            data-testid="filter-search"
            className="pl-8 bg-transparent border-[#22252F] text-sm"
          />
        </div>
        <FilterSelect testid="filter-source" placeholder="Source" value={filters.source_platform}
          onChange={(v) => setFilters({ ...filters, source_platform: v })}
          options={REVIEW_SOURCES.map((s) => ({ value: s, label: s }))} />
        <FilterSelect testid="filter-sentiment" placeholder="Sentiment" value={filters.sentiment}
          onChange={(v) => setFilters({ ...filters, sentiment: v })}
          options={SENTIMENTS.map((s) => ({ value: s.key, label: s.key }))} />
        <FilterSelect testid="filter-property" placeholder="Property" value={filters.property_id}
          onChange={(v) => setFilters({ ...filters, property_id: v })}
          options={properties.map((p) => ({ value: p.id, label: p.name }))} />
      </div>

      <div className="flex items-center gap-3 text-xs">
        <button
          onClick={() => setFilters({ ...filters, priority_only: !filters.priority_only })}
          data-testid="filter-priority"
          className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full border ${
            filters.priority_only
              ? "bg-[#E05A50]/15 text-[#E05A50] border-[#E05A50]"
              : "text-dim border-[#22252F] hover:text-white"
          }`}
        >
          <Flag className="w-3 h-3" /> Priority only
        </button>
        <FilterSelect testid="filter-responded" placeholder="Response" value={filters.responded}
          onChange={(v) => setFilters({ ...filters, responded: v })}
          options={[{ value: "yes", label: "Responded" }, { value: "no", label: "Unresponded" }]} />
        <button onClick={clearFilters} data-testid="filter-clear" className="inline-flex items-center gap-1 text-dim hover:text-white">
          <X className="w-3 h-3" /> Clear
        </button>
        <span className="ml-auto text-dim">{items.length} review{items.length === 1 ? "" : "s"}</span>
      </div>

      <div className="surface rounded-md overflow-hidden">
        {loading ? (
          <div className="p-8 text-dim text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center text-dim text-sm" data-testid="reviews-empty">
            No reviews match these filters yet.
          </div>
        ) : (
          <div className="divide-y divide-[#1A1D24]" data-testid="reviews-list">
            {items.map((r) => (
              <ReviewRow
                key={r.id}
                review={r}
                canEdit={isMgr}
                onEdit={() => setEditing(r)}
                onDelete={() => remove(r)}
              />
            ))}
          </div>
        )}
      </div>

      {creating && (
        <ReviewFormModal
          properties={properties}
          onClose={() => setCreating(false)}
          onSaved={onSaved}
        />
      )}
      {editing && (
        <ReviewFormModal
          initial={editing}
          properties={properties}
          onClose={() => setEditing(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

function KPI({ label, value, accent, icon, testid }) {
  return (
    <div className="surface rounded-md p-4" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-[0.18em] text-dim flex items-center gap-1">
        {icon} {label}
      </div>
      <div className="font-display text-2xl mt-1 tabular-nums" style={accent ? { color: accent } : {}}>
        {value ?? 0}
      </div>
    </div>
  );
}

function AnalyticsPanel({ title, rows, columns, testid }) {
  return (
    <div className="surface rounded-md p-4" data-testid={testid}>
      <div className="text-[11px] uppercase tracking-[0.22em] text-dim mb-3">{title}</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
            {columns.map((c) => (
              <th key={c.key} className={`pb-2 font-semibold text-${c.align}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-[#1A1D24]">
              {columns.map((c) => {
                const v = c.fmt ? c.fmt(row[c.key]) : row[c.key];
                return (
                  <td key={c.key} className={`py-1.5 text-${c.align} tabular-nums`}
                      style={c.accent && row[c.key] > 0 ? { color: c.accent } : {}}>
                    {v ?? "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
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

function ReviewRow({ review, canEdit, onEdit, onDelete }) {
  const s = findSentiment(review.sentiment);
  return (
    <div className="p-4 hover:bg-[#0F1117] transition-colors" data-testid={`review-row-${review.id}`}>
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 flex flex-col items-center gap-0.5">
          <div className="flex gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <Star
                key={n}
                className="w-3.5 h-3.5"
                fill={n <= (review.rating || 0) ? "#D9A05B" : "none"}
                color={n <= (review.rating || 0) ? "#D9A05B" : "#3A3F4C"}
              />
            ))}
          </div>
          <span className="text-[10px] uppercase tracking-[0.15em]" style={{ color: s.color }}>
            {review.sentiment}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-medium">{review.guest_name}</span>
            <span className="text-[10px] text-dim">·</span>
            <span className="text-[11px] text-dim">{review.source_platform}</span>
            {review.property_name && (
              <>
                <span className="text-[10px] text-dim">·</span>
                <span className="text-[11px] text-dim">{review.property_name}</span>
              </>
            )}
            <span className="text-[10px] text-dim">·</span>
            <span className="text-[11px] text-dim">{fmtReviewDate(review.review_date)}</span>
            {review.priority_flag && (
              <span className="ml-1 inline-flex items-center gap-1 text-[10px] text-[#E05A50] border border-[#E05A50]/60 px-1.5 py-0.5 rounded"
                    data-testid={`priority-badge-${review.id}`}>
                <Flag className="w-2.5 h-2.5" /> Priority
              </span>
            )}
            {review.response_sent
              ? <span className="text-[10px] text-[#5BD1A8] border border-[#5BD1A8]/40 px-1.5 py-0.5 rounded">Responded</span>
              : <span className="text-[10px] text-dim border border-[#22252F] px-1.5 py-0.5 rounded">Unresponded</span>
            }
          </div>
          {review.review_text && (
            <div className="text-xs text-[#C9CCD3] mt-2 whitespace-pre-wrap line-clamp-3">
              {review.review_text}
            </div>
          )}
          {review.category_tags?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {review.category_tags.map((t) => (
                <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-[#1A1D24] text-dim border border-[#22252F]">{t}</span>
              ))}
            </div>
          )}
          {review.management_response && (
            <div className="text-[11px] text-dim mt-2 pl-3 border-l-2 border-[#22252F] flex gap-1.5">
              <MessageSquare className="w-3 h-3 flex-shrink-0 mt-0.5" /> {review.management_response}
            </div>
          )}
        </div>
        {canEdit && (
          <div className="flex flex-col gap-1">
            <button onClick={onEdit} data-testid={`edit-review-${review.id}`} className="text-dim hover:text-white" title="Edit">
              <Pencil className="w-3.5 h-3.5" />
            </button>
            <button onClick={onDelete} data-testid={`delete-review-${review.id}`} className="text-dim hover:text-[#E05A50]" title="Delete">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
