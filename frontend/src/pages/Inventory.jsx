import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  INV_CATEGORIES, INV_STATUSES, findInvCat, findInvStatus,
} from "@/lib/inventory";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Package, AlertTriangle, Search, X, RefreshCw, Boxes, Plus,
} from "lucide-react";
import { toast } from "sonner";

export default function Inventory() {
  const { user } = useAuth();
  const isMgr = user?.role === "admin" || user?.role === "manager";

  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const [properties, setProperties] = useState([]);
  const [filters, setFilters] = useState({ category: "", property_id: "", status: "", q: "" });
  const [restockingId, setRestockingId] = useState(null);
  const [restockValue, setRestockValue] = useState("");

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    api.get("/properties").then((r) => setProperties(r.data.items || [])).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = {};
    if (filters.category) params.category = filters.category;
    if (filters.property_id) params.property_id = filters.property_id;
    if (filters.status) params.status = filters.status;
    api.get("/inventory", { params })
      .then((r) => {
        if (cancelled) return;
        setItems(r.data.items || []);
        setSummary(r.data.summary || null);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [version, filters.category, filters.property_id, filters.status]);

  const filtered = useMemo(() => {
    if (!filters.q.trim()) return items;
    const q = filters.q.toLowerCase();
    return items.filter((i) =>
      (i.label || "").toLowerCase().includes(q) ||
      (i.property_name || "").toLowerCase().includes(q) ||
      (i.subtype || "").toLowerCase().includes(q)
    );
  }, [items, filters.q]);

  const startRestock = (item) => {
    setRestockingId(item.id);
    setRestockValue(String(item.target_count));
  };

  const cancelRestock = () => { setRestockingId(null); setRestockValue(""); };

  const submitRestock = async (item) => {
    const n = parseInt(restockValue);
    if (Number.isNaN(n) || n < 0) {
      toast.error("Enter a valid count");
      return;
    }
    try {
      await api.post(`/inventory/${item.id}/restock`, { new_count: n });
      toast.success(`Restocked ${item.label} to ${n}`);
      cancelRestock();
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not restock");
    }
  };

  return (
    <div className="space-y-8" data-testid="inventory-page">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Operations</div>
          <h1 className="font-display text-3xl tracking-tight mt-1">Inventory</h1>
          <p className="text-sm text-dim mt-2 max-w-2xl">
            Stock levels across every property. When an item reaches its minimum threshold a
            restock task is auto-created and assigned to the property cleaner.
          </p>
        </div>
        <button
          onClick={refresh}
          data-testid="refresh-inventory"
          className="inline-flex items-center gap-2 text-xs border border-[#22252F] hover:border-[#3A3F4C] text-dim hover:text-white px-3 py-2 rounded-md h-fit"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Sync auto-tasks
        </button>
      </header>

      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3" data-testid="inv-summary">
          <Tile testid="inv-total"    label="Items"        value={summary.total} icon={<Boxes className="w-3.5 h-3.5" />} />
          <Tile testid="inv-ok"       label="On target"    value={summary.by_status.ok} accent="#5BD1A8" />
          <Tile testid="inv-below"    label="Below target" value={summary.by_status.below_target} accent="#D9A05B" />
          <Tile testid="inv-low"      label="Low stock"    value={summary.by_status.low} accent="#E0904E" icon={<AlertTriangle className="w-3.5 h-3.5" />} />
          <Tile testid="inv-out"      label="Out of stock" value={summary.by_status.out} accent="#E05A50" icon={<AlertTriangle className="w-3.5 h-3.5" />} />
        </div>
      )}

      <div className="surface rounded-md p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3" data-testid="inv-filters">
        <div className="lg:col-span-2 relative">
          <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-dim pointer-events-none" />
          <Input
            placeholder="Search label, property…"
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            data-testid="inv-filter-search"
            className="pl-8 bg-transparent border-[#22252F] text-sm"
          />
        </div>
        <FilterSelect testid="inv-filter-category" placeholder="Category" value={filters.category}
          onChange={(v) => setFilters({ ...filters, category: v })}
          options={INV_CATEGORIES.map((c) => ({ value: c.key, label: c.label }))} />
        <FilterSelect testid="inv-filter-status" placeholder="Status" value={filters.status}
          onChange={(v) => setFilters({ ...filters, status: v })}
          options={INV_STATUSES.map((s) => ({ value: s.key, label: s.label }))} />
        <FilterSelect testid="inv-filter-property" placeholder="Property" value={filters.property_id}
          onChange={(v) => setFilters({ ...filters, property_id: v })}
          options={properties.map((p) => ({ value: p.id, label: p.name }))} />
      </div>

      <div className="flex items-center gap-3 text-xs">
        <button
          onClick={() => setFilters({ category: "", property_id: "", status: "", q: "" })}
          data-testid="inv-filter-clear"
          className="inline-flex items-center gap-1 text-dim hover:text-white"
        >
          <X className="w-3 h-3" /> Clear
        </button>
        <span className="ml-auto text-dim">{filtered.length} item{filtered.length === 1 ? "" : "s"}</span>
      </div>

      <div className="surface rounded-md overflow-hidden">
        {loading ? (
          <div className="p-8 text-dim text-sm">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-dim text-sm" data-testid="inv-empty">
            No inventory items match these filters.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-[#0E1015]">
              <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
                <th className="text-left px-4 py-3 font-semibold">Item</th>
                <th className="text-left px-4 py-3 font-semibold">Property</th>
                <th className="text-center px-4 py-3 font-semibold">Stock</th>
                <th className="text-center px-4 py-3 font-semibold">Status</th>
                {isMgr && <th className="text-right px-4 py-3 font-semibold">Actions</th>}
              </tr>
            </thead>
            <tbody data-testid="inv-table-body">
              {filtered.map((it) => {
                const cat = findInvCat(it.category);
                const st = findInvStatus(it.status);
                const isRestocking = restockingId === it.id;
                return (
                  <tr key={it.id} data-testid={`inv-row-${it.id}`} className="tbl-row">
                    <td className="px-4 py-3">
                      <div className="text-white flex items-center gap-2">
                        <Package className="w-3.5 h-3.5" style={{ color: cat.color }} />
                        {it.label}
                      </div>
                      <div className="text-[10px] text-dim mt-0.5">
                        {cat.label} · {it.subtype} · {it.unit}
                      </div>
                      {it.linked_task_id && (
                        <div className="text-[10px] text-[#D9A05B] mt-0.5">↻ open restock task</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-dim">{it.property_name || "—"}</td>
                    <td className="px-4 py-3 text-center text-xs tabular-nums">
                      <span className="text-white">{it.current_count}</span>
                      <span className="text-dim"> / target {it.target_count}</span>
                      <div className="text-[10px] text-dim">min {it.min_threshold}</div>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span
                        className="text-[11px] inline-block px-2 py-0.5 rounded-full border"
                        style={{ color: st.color, borderColor: st.color + "55" }}
                        data-testid={`inv-status-${it.id}`}
                      >
                        {st.label}
                      </span>
                    </td>
                    {isMgr && (
                      <td className="px-4 py-3 text-right">
                        {isRestocking ? (
                          <div className="inline-flex gap-1.5">
                            <Input
                              type="number" min="0"
                              value={restockValue}
                              onChange={(e) => setRestockValue(e.target.value)}
                              data-testid={`inv-restock-input-${it.id}`}
                              className="w-20 bg-transparent border-[#22252F] text-xs h-7"
                            />
                            <button
                              onClick={() => submitRestock(it)}
                              data-testid={`inv-restock-submit-${it.id}`}
                              className="text-[11px] bg-brand text-black font-medium px-2 rounded-md hover:opacity-90"
                            >
                              Save
                            </button>
                            <button onClick={cancelRestock} className="text-[11px] text-dim hover:text-white px-1">×</button>
                          </div>
                        ) : (
                          <button
                            onClick={() => startRestock(it)}
                            data-testid={`inv-restock-${it.id}`}
                            className="inline-flex items-center gap-1 text-xs text-[#5BD1A8] hover:text-white"
                          >
                            <Plus className="w-3.5 h-3.5" /> Restock
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Tile({ label, value, accent, icon, testid }) {
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
