import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import {
  REVIEW_SOURCES, REVIEW_CATEGORIES, SENTIMENTS, suggestSentiment,
} from "@/lib/reviews";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Star, X, Save, Flag } from "lucide-react";
import { toast } from "sonner";

const BLANK = {
  guest_name: "",
  guest_email: "",
  property_name: "",
  reservation_id: "",
  rating: 5,
  source_platform: "Airbnb",
  review_text: "",
  review_date: new Date().toISOString().slice(0, 10),
  category_tags: [],
  sentiment: "Positive",
  management_response: "",
  response_sent: false,
  internal_notes: "",
  priority_flag_manual: null,
};

export default function ReviewFormModal({ initial, properties, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [draft, setDraft] = useState(() => (isEdit
    ? {
        ...BLANK, ...initial,
        guest_name: initial.guest_name || "",
        guest_email: initial.guest_email || "",
        property_name: initial.property_name || "",
        reservation_id: initial.reservation_id || "",
        review_text: initial.review_text || "",
        management_response: initial.management_response || "",
        internal_notes: initial.internal_notes || "",
        review_date: initial.review_date || BLANK.review_date,
        category_tags: initial.category_tags || [],
      }
    : BLANK
  ));
  const [saving, setSaving] = useState(false);
  const [sentimentManual, setSentimentManual] = useState(!!isEdit);

  useEffect(() => {
    if (!sentimentManual) {
      setDraft((d) => ({ ...d, sentiment: suggestSentiment(d.rating) }));
    }
  }, [draft.rating, sentimentManual]);

  const set = (patch) => setDraft({ ...draft, ...patch });
  const toggleTag = (t) => {
    setDraft({
      ...draft,
      category_tags: draft.category_tags.includes(t)
        ? draft.category_tags.filter((x) => x !== t)
        : [...draft.category_tags, t],
    });
  };

  const submit = async () => {
    if (!draft.guest_name.trim()) {
      toast.error("Guest name is required");
      return;
    }
    if (draft.rating < 1 || draft.rating > 5) {
      toast.error("Rating must be 1–5");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...draft,
        guest_email: draft.guest_email.trim().toLowerCase() || null,
        rating: parseInt(draft.rating),
        property_name: draft.property_name || "",
        review_date: draft.review_date || null,
        review_text: draft.review_text || "",
        management_response: draft.management_response || "",
        internal_notes: draft.internal_notes || "",
      };
      if (isEdit) {
        const r = await api.put(`/reviews/${initial.id}`, payload);
        onSaved(r.data, false);
      } else {
        const r = await api.post("/reviews", payload);
        onSaved(r.data, true);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-start justify-center p-4 overflow-y-auto"
      data-testid="review-form-modal"
      onClick={onClose}
    >
      <div
        className="surface rounded-md w-full max-w-2xl p-6 space-y-4 my-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start">
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-dim">
              {isEdit ? "Edit review" : "New review"}
            </div>
            <h2 className="font-display text-xl mt-1">{isEdit ? "Update guest review" : "Log a guest review"}</h2>
          </div>
          <button onClick={onClose} data-testid="review-form-close" className="text-dim hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <Label>Guest name *</Label>
            <Input
              value={draft.guest_name}
              onChange={(e) => set({ guest_name: e.target.value })}
              data-testid="review-guest-name"
              autoFocus
              className="mt-1 bg-transparent border-[#22252F]"
              placeholder="Jane Doe"
            />
          </div>
          <div>
            <Label>Guest email</Label>
            <Input
              type="email"
              value={draft.guest_email}
              onChange={(e) => set({ guest_email: e.target.value })}
              data-testid="review-guest-email"
              className="mt-1 bg-transparent border-[#22252F]"
              placeholder="guest@example.com"
            />
          </div>
          <div>
            <Label>Review date</Label>
            <Input
              type="date"
              value={draft.review_date}
              onChange={(e) => set({ review_date: e.target.value })}
              data-testid="review-date"
              className="mt-1 bg-transparent border-[#22252F]"
            />
          </div>

          {/* Star rating */}
          <div>
            <Label>Rating</Label>
            <div className="flex gap-1 mt-2" data-testid="review-rating">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => set({ rating: n })}
                  data-testid={`review-star-${n}`}
                  className="p-0.5 hover:scale-110 transition-transform"
                  aria-label={`${n} stars`}
                >
                  <Star
                    className="w-6 h-6"
                    fill={n <= draft.rating ? "#D9A05B" : "none"}
                    color={n <= draft.rating ? "#D9A05B" : "#3A3F4C"}
                  />
                </button>
              ))}
            </div>
          </div>

          <div>
            <Label>Source platform</Label>
            <Select value={draft.source_platform} onValueChange={(v) => set({ source_platform: v })}>
              <SelectTrigger data-testid="review-source" className="mt-1 bg-transparent border-[#22252F]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#12141A] border-[#22252F] text-white max-h-72">
                {REVIEW_SOURCES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label>Property</Label>
            <Select
              value={draft.property_id || draft.property_name || "__none__"}
              onValueChange={(v) => {
                if (v === "__none__") { set({ property_id: null, property_name: "" }); return; }
                const p = properties.find((pp) => pp.id === v);
                set({ property_id: v, property_name: p?.name || v });
              }}
            >
              <SelectTrigger data-testid="review-property" className="mt-1 bg-transparent border-[#22252F]">
                <SelectValue placeholder="— None —" />
              </SelectTrigger>
              <SelectContent className="bg-[#12141A] border-[#22252F] text-white max-h-72">
                <SelectItem value="__none__">— None —</SelectItem>
                {properties.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {/* Category tag chips */}
          <div className="sm:col-span-2">
            <Label>Category tags</Label>
            <div className="flex flex-wrap gap-2 mt-2" data-testid="review-categories">
              {REVIEW_CATEGORIES.map((tag) => {
                const active = draft.category_tags.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag)}
                    data-testid={`chip-${tag.toLowerCase().replace(/\s+/g, "-")}`}
                    className={`px-3 py-1 text-xs rounded-full border transition-colors whitespace-nowrap ${
                      active
                        ? "bg-[#D9A05B]/15 text-[#D9A05B] border-[#D9A05B]"
                        : "text-dim border-[#22252F] hover:text-white hover:border-[#3A3F4C]"
                    }`}
                  >
                    {tag}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="sm:col-span-2">
            <Label>Review text</Label>
            <Textarea
              value={draft.review_text}
              onChange={(e) => set({ review_text: e.target.value })}
              data-testid="review-text"
              rows={3}
              className="mt-1 bg-transparent border-[#22252F]"
              placeholder="What did the guest say?"
            />
          </div>

          <div>
            <Label>Sentiment (auto from rating — override if needed)</Label>
            <Select
              value={draft.sentiment}
              onValueChange={(v) => { set({ sentiment: v }); setSentimentManual(true); }}
            >
              <SelectTrigger data-testid="review-sentiment" className="mt-1 bg-transparent border-[#22252F]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#12141A] border-[#22252F] text-white">
                {SENTIMENTS.map((s) => (
                  <SelectItem key={s.key} value={s.key}>
                    <span style={{ color: s.color }}>{s.key}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label>Reservation ID (optional)</Label>
            <Input
              value={draft.reservation_id || ""}
              onChange={(e) => set({ reservation_id: e.target.value })}
              data-testid="review-reservation"
              className="mt-1 bg-transparent border-[#22252F] font-mono text-xs"
            />
          </div>

          <div className="sm:col-span-2">
            <Label>Management response (draft or log)</Label>
            <Textarea
              value={draft.management_response}
              onChange={(e) => set({ management_response: e.target.value })}
              data-testid="review-mgmt-response"
              rows={2}
              className="mt-1 bg-transparent border-[#22252F]"
              placeholder="Your reply to the guest…"
            />
          </div>

          <div className="flex items-center gap-3">
            <Switch
              checked={draft.response_sent}
              onCheckedChange={(v) => set({ response_sent: v })}
              data-testid="review-response-sent"
            />
            <span className="text-sm">{draft.response_sent ? "Response sent" : "Response NOT sent"}</span>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                const next = draft.priority_flag_manual === true ? null : true;
                set({ priority_flag_manual: next });
              }}
              data-testid="review-priority-toggle"
              className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border ${
                draft.priority_flag_manual === true
                  ? "bg-[#E05A50]/15 text-[#E05A50] border-[#E05A50]"
                  : "text-dim border-[#22252F] hover:text-white"
              }`}
            >
              <Flag className="w-3 h-3" />
              {draft.priority_flag_manual === true ? "Priority flag ON (manual)" : "Flag as priority"}
            </button>
          </div>

          <div className="sm:col-span-2">
            <Label>Internal notes (not guest-facing)</Label>
            <Textarea
              value={draft.internal_notes}
              onChange={(e) => set({ internal_notes: e.target.value })}
              data-testid="review-internal-notes"
              rows={2}
              className="mt-1 bg-transparent border-[#22252F]"
              placeholder="Anything the team should know…"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm text-dim hover:text-white px-3 py-2">Cancel</button>
          <button
            onClick={submit}
            disabled={saving}
            data-testid="review-submit"
            className="inline-flex items-center gap-2 bg-brand text-black text-sm font-medium px-4 py-2 rounded-md hover:opacity-90 disabled:opacity-50"
          >
            <Save className="w-4 h-4" /> {saving ? "Saving…" : (isEdit ? "Save changes" : "Save review")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Label({ children }) {
  return <label className="text-[10px] uppercase tracking-[0.15em] text-dim">{children}</label>;
}
