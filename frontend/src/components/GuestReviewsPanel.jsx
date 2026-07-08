import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { findSentiment, fmtReviewDate } from "@/lib/reviews";
import { Star, Flag, MessageSquare } from "lucide-react";

// Reviews panel for /guests/{id} — lists all reviews for a given guest email.
export default function GuestReviewsPanel({ email }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!email) { setItems([]); setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    api.get("/reviews/for-guest", { params: { email } })
      .then((r) => { if (!cancelled) { setItems(r.data.items || []); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [email]);

  if (loading) return null;

  return (
    <div className="surface rounded-md p-5" data-testid="guest-reviews-panel">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] uppercase tracking-[0.22em] text-dim">
          Reviews ({items.length})
        </div>
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-dim italic">No reviews from this guest yet.</div>
      ) : (
        <div className="space-y-3">
          {items.map((r) => {
            const s = findSentiment(r.sentiment);
            return (
              <div key={r.id} className="border-t border-[#1A1D24] pt-3 first:border-t-0 first:pt-0"
                   data-testid={`guest-review-${r.id}`}>
                <div className="flex items-center gap-2 flex-wrap text-[11px]">
                  <div className="flex gap-0.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Star key={n} className="w-3 h-3"
                            fill={n <= (r.rating || 0) ? "#D9A05B" : "none"}
                            color={n <= (r.rating || 0) ? "#D9A05B" : "#3A3F4C"} />
                    ))}
                  </div>
                  <span style={{ color: s.color }} className="uppercase tracking-[0.15em]">{r.sentiment}</span>
                  <span className="text-dim">·</span>
                  <span className="text-dim">{r.source_platform}</span>
                  {r.property_name && (
                    <>
                      <span className="text-dim">·</span>
                      <span className="text-dim">{r.property_name}</span>
                    </>
                  )}
                  <span className="text-dim">·</span>
                  <span className="text-dim">{fmtReviewDate(r.review_date)}</span>
                  {r.priority_flag && (
                    <span className="text-[10px] text-[#E05A50] border border-[#E05A50]/60 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
                      <Flag className="w-2.5 h-2.5" /> Priority
                    </span>
                  )}
                </div>
                {r.review_text && (
                  <div className="text-xs text-[#C9CCD3] mt-2 whitespace-pre-wrap">{r.review_text}</div>
                )}
                {r.management_response && (
                  <div className="text-[11px] text-dim mt-2 pl-3 border-l-2 border-[#22252F] flex gap-1.5">
                    <MessageSquare className="w-3 h-3 flex-shrink-0 mt-0.5" /> {r.management_response}
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
