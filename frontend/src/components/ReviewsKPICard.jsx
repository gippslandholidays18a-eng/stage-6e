import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Star, Flag, MessageCircle, ArrowRight } from "lucide-react";

// Dashboard KPI card showing key review metrics (avg rating, response rate, priority open).
export default function ReviewsKPICard() {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.get("/reviews/analytics")
      .then((r) => { if (!cancelled) { setAnalytics(r.data); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <section data-testid="reviews-kpi-card" className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Guest reviews</div>
        <Link to="/reviews" data-testid="reviews-kpi-go" className="text-[11px] text-dim hover:text-white inline-flex items-center gap-1">
          Open review board <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Link to="/reviews" data-testid="reviews-kpi-avg" className="surface rounded-md p-5 hover:border-[#3A3F4C] transition-colors">
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-[0.18em] text-dim">Average rating</div>
            <Star className="w-3.5 h-3.5 opacity-60" color="#D9A05B" />
          </div>
          <div className="font-display text-3xl font-light tracking-tighter mt-2 tabular-nums" style={{ color: "#D9A05B" }}>
            {loading ? "…" : (analytics?.avg_rating != null ? `${analytics.avg_rating}` : "—")}
            <span className="text-sm text-dim ml-1">/5</span>
          </div>
          <div className="text-[11px] text-dim mt-2">{analytics?.total ?? 0} total reviews</div>
        </Link>

        <Link to="/reviews" data-testid="reviews-kpi-response" className="surface rounded-md p-5 hover:border-[#3A3F4C] transition-colors">
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-[0.18em] text-dim">Response rate</div>
            <MessageCircle className="w-3.5 h-3.5 opacity-60" color="#5BD1A8" />
          </div>
          <div className="font-display text-3xl font-light tracking-tighter mt-2 tabular-nums" style={{ color: "#5BD1A8" }}>
            {loading ? "…" : (analytics?.response_rate != null ? `${analytics.response_rate}%` : "—")}
          </div>
          <div className="text-[11px] text-dim mt-2">Replies sent to guests</div>
        </Link>

        <Link to="/reviews?priority_only=1" data-testid="reviews-kpi-priority" className="surface rounded-md p-5 hover:border-[#3A3F4C] transition-colors"
              style={analytics?.priority_open > 0 ? { borderColor: "#E05A50" + "55" } : {}}>
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-[0.18em] text-dim">Priority open</div>
            <Flag className="w-3.5 h-3.5 opacity-60" color="#E05A50" />
          </div>
          <div className="font-display text-3xl font-light tracking-tighter mt-2 tabular-nums" style={{ color: (analytics?.priority_open || 0) > 0 ? "#E05A50" : "#F2F3F5" }}>
            {loading ? "…" : (analytics?.priority_open ?? 0)}
          </div>
          <div className="text-[11px] text-dim mt-2">Low rating + unresponded</div>
        </Link>
      </div>
    </section>
  );
}
