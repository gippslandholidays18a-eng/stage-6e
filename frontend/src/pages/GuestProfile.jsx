import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, fmtMoney, fmtNumber, fmtDate, SOURCE_COLORS } from "@/lib/api";
import { SegmentBadge } from "@/components/SegmentBadge";
import { ChevronLeft, AlertTriangle, Mail, Building2, Calendar } from "lucide-react";
import GuestReviewsPanel from "@/components/GuestReviewsPanel";

export default function GuestProfile() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get(`/guests/${encodeURIComponent(id)}`)
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="text-dim text-sm">Loading profile…</div>;
  if (error || !data) return <div className="text-[#E05A50] text-sm">{error}</div>;

  const { guest, completed, cancelled } = data;
  const hasCancellations = cancelled.length > 0;

  return (
    <div data-testid="guest-profile-page" className="space-y-8 max-w-6xl">
      <Link to="/segments" className="inline-flex items-center gap-1 text-xs text-dim hover:text-white">
        <ChevronLeft className="w-3.5 h-3.5" /> Back to segments
      </Link>

      {/* Header */}
      <header className="flex flex-col sm:flex-row gap-6 sm:items-center">
        <div className="w-16 h-16 rounded-md bg-[#1A1D24] border divider flex items-center justify-center font-display text-xl">
          {guest.initials}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="font-display text-3xl tracking-tight">
            {guest.first_name} {guest.last_name}
          </h1>
          <div className="text-sm text-dim flex items-center gap-2 mt-1">
            <Mail className="w-3.5 h-3.5" /> {guest.email}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3" data-testid="guest-segment-badges">
            {hasCancellations && (
              <span
                data-testid="cancellation-warning-badge"
                className="text-[10px] px-2 py-0.5 rounded border inline-flex items-center gap-1"
                style={{ color: "#E05A50", borderColor: "#E05A5044", backgroundColor: "#E05A5014" }}
              >
                <AlertTriangle className="w-3 h-3" /> {guest.cancellation_count} cancellation{guest.cancellation_count > 1 ? "s" : ""}
              </span>
            )}
            {(guest.segments || []).map((s) => (
              <SegmentBadge key={s} name={s} />
            ))}
            {(guest.segments || []).length === 0 && (
              <span className="text-[10px] text-dim">No segments assigned</span>
            )}
          </div>
        </div>
        <PriorityIndicator score={guest.remarketing_priority_score} recovered={guest.recovered} />
      </header>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="Total stays" value={fmtNumber(guest.total_stays)} />
        <Stat label="Lifetime spend" value={fmtMoney(guest.lifetime_spend)} />
        <Stat label="Avg booking value" value={fmtMoney(guest.avg_booking_value)} />
        <Stat label="Avg length of stay" value={`${guest.avg_length_of_stay || 0} nights`} />
        <Stat label="First stay" value={fmtDate(guest.first_stay_date)} />
        <Stat label="Last stay" value={fmtDate(guest.last_stay_date)} />
        <Stat label="Primary channel" value={guest.primary_channel} />
        <Stat label="Most used source" value={guest.most_used_source || "—"} />
        <Stat label="Cancellation rate" value={`${guest.cancellation_rate || 0}%`} />
        <Stat label="Cancellations" value={fmtNumber(guest.cancellation_count)} />
        <Stat label="Properties stayed" value={fmtNumber((guest.properties || []).length)} />
        <Stat label="Recovered" value={guest.recovered ? "Yes" : "No"} />
      </div>

      {/* Properties */}
      {(guest.properties || []).length > 0 && (
        <section className="surface rounded-md p-6">
          <h2 className="font-display text-lg">Properties stayed at</h2>
          <div className="flex flex-wrap gap-2 mt-4">
            {guest.properties.map((p) => (
              <span
                key={p}
                className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border divider bg-[#0F1116]"
              >
                <Building2 className="w-3 h-3 text-[#D9A05B]" /> {p}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Completed bookings */}
      <BookingsTable
        title="Completed bookings"
        testid="completed-bookings-table"
        rows={completed}
        emptyMsg="No completed bookings yet."
      />

      {/* Cancellation history */}
      {hasCancellations && (
        <BookingsTable
          title="Cancellation history"
          testid="cancellation-history-table"
          rows={cancelled}
          tone="danger"
        />
      )}

      {/* Guest reviews */}
      <GuestReviewsPanel email={guest.email} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="surface rounded-md p-4">
      <div className="text-[10px] uppercase tracking-[0.15em] text-dim">{label}</div>
      <div className="font-display text-lg mt-2 truncate">{value}</div>
    </div>
  );
}

function PriorityIndicator({ score, recovered }) {
  let band = "Low";
  let color = "#419B72";
  if (score >= 70) {
    band = "High";
    color = "#E05A50";
  } else if (score >= 40) {
    band = "Medium";
    color = "#D9A05B";
  }
  return (
    <div
      data-testid="remarketing-priority"
      className="surface rounded-md p-4 min-w-[180px]"
      style={{ borderColor: `${color}55` }}
    >
      <div className="text-[10px] uppercase tracking-[0.15em] text-dim">Remarketing priority</div>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="font-display text-3xl tabular-nums" style={{ color }}>
          {score}
        </span>
        <span className="text-[11px] uppercase tracking-wider" style={{ color }}>
          {band}
        </span>
      </div>
      <div className="w-full h-1.5 bg-[#0E1015] mt-2 rounded">
        <div
          className="h-full rounded"
          style={{ width: `${Math.max(2, score)}%`, backgroundColor: color }}
        />
      </div>
      {recovered && <div className="text-[10px] text-[#419B72] mt-2">Recovered guest</div>}
    </div>
  );
}

function BookingsTable({ title, rows, testid, tone, emptyMsg }) {
  return (
    <section className="surface rounded-md overflow-hidden">
      <div className="px-6 py-4 border-b divider flex items-center gap-2">
        {tone === "danger" && <AlertTriangle className="w-4 h-4 text-[#E05A50]" />}
        <h2 className="font-display text-lg">{title}</h2>
        <span className="text-xs text-dim">· {rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="px-6 py-10 text-center text-dim text-sm">{emptyMsg || "No records."}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0E1015]">
              <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
                <th className="text-left px-4 py-3 font-semibold">Reservation</th>
                <th className="text-left px-4 py-3 font-semibold">Property</th>
                <th className="text-left px-4 py-3 font-semibold">Check-in</th>
                <th className="text-right px-4 py-3 font-semibold">Nights</th>
                <th className="text-right px-4 py-3 font-semibold">Value</th>
                <th className="text-left px-4 py-3 font-semibold">Source</th>
              </tr>
            </thead>
            <tbody data-testid={testid}>
              {rows.map((r) => (
                <tr key={r.id} className="tbl-row">
                  <td className="px-4 py-3 font-mono text-[11px] text-dim">{r.reservation_id}</td>
                  <td className="px-4 py-3">{r.property_name || "—"}</td>
                  <td className="px-4 py-3 text-dim">
                    <span className="inline-flex items-center gap-1.5">
                      <Calendar className="w-3 h-3" />
                      {fmtDate(r.checkin_date)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-dim">{r.nights ?? "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fmtMoney(r.booking_value)}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5 text-xs">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: SOURCE_COLORS[r.classified_source] || "#6B7280" }}
                      />
                      {r.classified_source}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
