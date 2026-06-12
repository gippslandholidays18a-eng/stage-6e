import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  INV_CATEGORIES, INV_STATUSES, findInvCat, findInvStatus,
} from "@/lib/inventory";
import {
  Package, Plus, RefreshCw, Trash2, Save, X,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";

export default function PropertyInventoryPanel({ propertyId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState(null);
  const [adding, setAdding] = useState(false);
  const [addDraft, setAddDraft] = useState({
    category: "linens", subtype: "", label: "", unit: "each",
    min_threshold: 1, target_count: 3, current_count: 3, notes: "",
  });
  const [restockingId, setRestockingId] = useState(null);
  const [restockValue, setRestockValue] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(`/inventory?property_id=${propertyId}`)
      .then((r) => { if (!cancelled) { setItems(r.data.items || []); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [propertyId, version]);

  const refresh = () => setVersion((v) => v + 1);

  const seed = async () => {
    try {
      const r = await api.post(`/inventory/seed-defaults?property_id=${propertyId}`);
      toast.success(`Seeded ${r.data.inserted} item(s)`);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not seed");
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Remove "${item.label}" from this property?`)) return;
    try {
      await api.delete(`/inventory/${item.id}`);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not delete");
    }
  };

  const startEdit = (item) => {
    setEditingId(item.id);
    setEditDraft({
      label: item.label, unit: item.unit,
      min_threshold: item.min_threshold, target_count: item.target_count,
      notes: item.notes || "", active: !!item.active,
    });
  };

  const saveEdit = async () => {
    try {
      await api.put(`/inventory/${editingId}`, {
        label: editDraft.label, unit: editDraft.unit,
        min_threshold: parseInt(editDraft.min_threshold) || 0,
        target_count: parseInt(editDraft.target_count) || 0,
        notes: editDraft.notes, active: editDraft.active,
      });
      toast.success("Saved");
      setEditingId(null); setEditDraft(null);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const submitAdd = async () => {
    if (!addDraft.label.trim() || !addDraft.subtype.trim()) {
      toast.error("Label and subtype are required");
      return;
    }
    try {
      await api.post("/inventory", {
        property_id: propertyId,
        category: addDraft.category,
        subtype: addDraft.subtype.trim(),
        label: addDraft.label.trim(),
        unit: addDraft.unit || "each",
        min_threshold: parseInt(addDraft.min_threshold) || 0,
        target_count: parseInt(addDraft.target_count) || 1,
        current_count: parseInt(addDraft.current_count) || 0,
        notes: addDraft.notes,
      });
      toast.success("Item added");
      setAdding(false);
      setAddDraft({ category: "linens", subtype: "", label: "", unit: "each", min_threshold: 1, target_count: 3, current_count: 3, notes: "" });
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not add");
    }
  };

  const submitRestock = async (item) => {
    const n = parseInt(restockValue);
    if (Number.isNaN(n) || n < 0) { toast.error("Enter a valid count"); return; }
    try {
      await api.post(`/inventory/${item.id}/restock`, { new_count: n });
      toast.success("Restocked");
      setRestockingId(null);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not restock");
    }
  };

  return (
    <div className="space-y-3" data-testid={`inventory-panel-${propertyId}`}>
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.18em] text-dim">
          Inventory ({items.length})
        </div>
        <div className="flex gap-2">
          <button onClick={seed} data-testid="inventory-seed-defaults" className="text-[11px] text-dim hover:text-white inline-flex items-center gap-1">
            <RefreshCw className="w-3 h-3" /> Seed defaults
          </button>
          <button onClick={() => setAdding(true)} data-testid="inventory-add-custom" className="text-[11px] text-[#D9A05B] hover:text-white inline-flex items-center gap-1">
            <Plus className="w-3 h-3" /> Add custom item
          </button>
        </div>
      </div>

      {adding && (
        <div className="surface rounded-md p-3 space-y-2" data-testid="inventory-add-editor">
          <div className="grid grid-cols-2 gap-2">
            <Select value={addDraft.category} onValueChange={(v) => setAddDraft({ ...addDraft, category: v })}>
              <SelectTrigger data-testid="inventory-add-category" className="bg-transparent border-[#22252F] text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#12141A] border-[#22252F] text-white">
                {INV_CATEGORIES.map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input value={addDraft.unit} onChange={(e) => setAddDraft({ ...addDraft, unit: e.target.value })}
              placeholder="Unit (each, bottle…)" data-testid="inventory-add-unit"
              className="bg-transparent border-[#22252F] text-sm" />
            <Input value={addDraft.subtype} onChange={(e) => setAddDraft({ ...addDraft, subtype: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
              placeholder="Subtype key" data-testid="inventory-add-subtype"
              className="bg-transparent border-[#22252F] text-sm font-mono" />
            <Input value={addDraft.label} onChange={(e) => setAddDraft({ ...addDraft, label: e.target.value })}
              placeholder="Label" data-testid="inventory-add-label"
              className="bg-transparent border-[#22252F] text-sm" />
            <Input type="number" min="0" value={addDraft.min_threshold} onChange={(e) => setAddDraft({ ...addDraft, min_threshold: e.target.value })}
              placeholder="Min" data-testid="inventory-add-min"
              className="bg-transparent border-[#22252F] text-sm" />
            <Input type="number" min="0" value={addDraft.target_count} onChange={(e) => setAddDraft({ ...addDraft, target_count: e.target.value })}
              placeholder="Target" data-testid="inventory-add-target"
              className="bg-transparent border-[#22252F] text-sm" />
            <Input type="number" min="0" value={addDraft.current_count} onChange={(e) => setAddDraft({ ...addDraft, current_count: e.target.value })}
              placeholder="Current count" data-testid="inventory-add-current"
              className="bg-transparent border-[#22252F] text-sm" />
            <Input value={addDraft.notes} onChange={(e) => setAddDraft({ ...addDraft, notes: e.target.value })}
              placeholder="Notes"
              className="bg-transparent border-[#22252F] text-sm" />
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setAdding(false)} className="text-xs text-dim hover:text-white px-3 py-1.5">Cancel</button>
            <button onClick={submitAdd} data-testid="inventory-add-submit" className="text-xs bg-brand text-black font-medium px-3 py-1.5 rounded-md hover:opacity-90">
              <Save className="w-3 h-3 inline mr-1" /> Add
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-xs text-dim p-3">Loading…</div>
      ) : items.length === 0 ? (
        <div className="text-xs text-dim italic p-3">No inventory items yet · click “Seed defaults” to start.</div>
      ) : (
        <div className="space-y-1.5">
          {items.map((it) => {
            const cat = findInvCat(it.category);
            const st = findInvStatus(it.status);
            const isEditing = editingId === it.id;
            const isRestocking = restockingId === it.id;
            return (
              <div key={it.id} data-testid={`inventory-item-${it.id}`} className="border border-[#22252F] rounded-md p-2.5">
                {!isEditing && !isRestocking ? (
                  <div className="flex items-center gap-3 text-xs">
                    <Package className="w-3.5 h-3.5 flex-shrink-0" style={{ color: cat.color }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-white">{it.label}</div>
                      <div className="text-[10px] text-dim">
                        {cat.label} · {it.current_count}/{it.target_count} {it.unit} · min {it.min_threshold}
                      </div>
                    </div>
                    <span className="text-[10px] inline-block px-2 py-0.5 rounded-full border"
                      style={{ color: st.color, borderColor: st.color + "55" }}
                      data-testid={`inventory-status-${it.id}`}>
                      {st.label}
                    </span>
                    <button onClick={() => { setRestockingId(it.id); setRestockValue(String(it.target_count)); }}
                      data-testid={`inventory-restock-${it.id}`} title="Restock"
                      className="text-[#5BD1A8] hover:text-white">
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => startEdit(it)} data-testid={`inventory-edit-${it.id}`} title="Edit" className="text-dim hover:text-white">✎</button>
                    <button onClick={() => remove(it)} data-testid={`inventory-delete-${it.id}`} title="Remove" className="text-dim hover:text-[#E05A50]">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : isRestocking ? (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-white">{it.label} →</span>
                    <Input type="number" min="0" value={restockValue}
                      onChange={(e) => setRestockValue(e.target.value)}
                      data-testid={`inventory-restock-input-${it.id}`}
                      className="w-20 bg-transparent border-[#22252F] text-xs h-7" />
                    <button onClick={() => submitRestock(it)} data-testid={`inventory-restock-submit-${it.id}`}
                      className="text-[11px] bg-brand text-black font-medium px-2 py-1 rounded-md hover:opacity-90">Save</button>
                    <button onClick={() => setRestockingId(null)} className="text-[11px] text-dim hover:text-white">×</button>
                  </div>
                ) : (
                  <div className="space-y-2" data-testid={`inventory-editor-${it.id}`}>
                    <div className="grid grid-cols-2 gap-2">
                      <Input value={editDraft.label} onChange={(e) => setEditDraft({ ...editDraft, label: e.target.value })}
                        data-testid={`inventory-edit-label-${it.id}`}
                        className="bg-transparent border-[#22252F] text-xs" />
                      <Input value={editDraft.unit} onChange={(e) => setEditDraft({ ...editDraft, unit: e.target.value })}
                        placeholder="Unit"
                        className="bg-transparent border-[#22252F] text-xs" />
                      <Input type="number" min="0" value={editDraft.min_threshold}
                        onChange={(e) => setEditDraft({ ...editDraft, min_threshold: e.target.value })}
                        placeholder="Min"
                        data-testid={`inventory-edit-min-${it.id}`}
                        className="bg-transparent border-[#22252F] text-xs" />
                      <Input type="number" min="0" value={editDraft.target_count}
                        onChange={(e) => setEditDraft({ ...editDraft, target_count: e.target.value })}
                        placeholder="Target"
                        data-testid={`inventory-edit-target-${it.id}`}
                        className="bg-transparent border-[#22252F] text-xs" />
                      <div className="flex items-center gap-2 col-span-2">
                        <Switch checked={editDraft.active} onCheckedChange={(v) => setEditDraft({ ...editDraft, active: v })} />
                        <span className="text-xs text-dim">{editDraft.active ? "Active" : "Paused"}</span>
                      </div>
                      <Input value={editDraft.notes} onChange={(e) => setEditDraft({ ...editDraft, notes: e.target.value })}
                        placeholder="Notes"
                        className="bg-transparent border-[#22252F] text-xs col-span-2" />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button onClick={() => { setEditingId(null); setEditDraft(null); }} className="text-[11px] text-dim hover:text-white">Cancel</button>
                      <button onClick={saveEdit} data-testid={`inventory-edit-save-${it.id}`} className="text-[11px] bg-brand text-black font-medium px-3 py-1 rounded-md hover:opacity-90">Save</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
