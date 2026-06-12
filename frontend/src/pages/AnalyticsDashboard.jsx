import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAUD, fmtNumber, fmtPct, SOURCE_COLORS, CHANNEL_COLORS } from "@/lib/api";
import AnalyticsFilters, { buildParams } from "@/components/AnalyticsFilters";
import { SegmentBadge } from "@/components/SegmentBadge";
import TasksAttentionWidget from "@/components/TasksAttentionWidget";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
  LineChart,
  Line,
  PieChart,
  Pie,
  Legend,
} from "recharts";
import { TrendingUp, Calendar, Users, DollarSign, BarChart3, ArrowRight, FileDown } from "lucide-react";

const tooltipStyle = {
  backgroundColor: "#12141A",
  border: "1px solid #22252F",
  borderRadius: 6,
  fontSize: 12,
  color: "#F2F3F5",
};

const SECTIONS = [
  { key: "revenue", label: "Revenue", icon: DollarSign },
  { key: "bookings", label: "Bookings", icon: Calendar },
  { key: "guests", label: "Guests", icon: Users },
  { key: "conversion", label: "Conversion", icon: TrendingUp },
  { key: "clv", label: "Lifetime value", icon: BarChart3 },
];

export default function AnalyticsDashboard() {
  const [filters, setFilters] = useState({
    preset: "365",
    start_date: "",
    end_date: "",
    property_name: "all",
  });
  const [section, setSection] = useState("revenue");
  const [data, setData] = useState({});

  const params = useMemo(() => buildParams(filters), [filters]);

  const cacheKey = useMemo(() => JSON.stringify({ section, params }), [section, params]);
  const current = data[cacheKey];

  useEffect(() => {
    if (current) return;
    let cancelled = false;
    api.get(`/analytics/${section}`, { params }).then((r) => {
      if (cancelled) return;
      setData((d) => ({ ...d, [cacheKey]: r.data }));
    });
    return () => {
      cancelled = true;
    };
  }, [cacheKey, current, section, params]);

  return (
    <div data-testid="analytics-dashboard" className="space-y-6">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Analytics</div>
          <h1 className="font-display text-3xl tracking-tight mt-1">Performance dashboard</h1>
          <p className="text-sm text-dim mt-2 max-w-2xl">
            Revenue, bookings, guests, conversion and lifetime value — filterable by period and property.
          </p>
        </div>
        <Link
          to="/reports"
          data-testid="cta-reports"
          className="inline-flex items-center gap-2 bg-transparent border border-[#22252F] text-sm text-white px-4 py-2 rounded-md hover:bg-[#14161D]"
        >
          <FileDown className="w-4 h-4" /> Reports
        </Link>
      </header>

      <AnalyticsFilters value={filters} onChange={setFilters} />

      <TasksAttentionWidget />

      {/* Section tabs */}
      <div className="flex flex-wrap gap-1 border-b divider" data-testid="section-tabs">
        {SECTIONS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setSection(key)}
            data-testid={`tab-${key}`}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
              section === key
                ? "border-[#D9A05B] text-white"
                : "border-transparent text-dim hover:text-white"
            }`}
          >
            <Icon className="w-3.5 h-3.5" /> {label}
          </button>
        ))}
      </div>

      <div data-testid={`section-content-${section}`}>
        {!current ? (
          <SkeletonGrid />
        ) : section === "revenue" ? (
          <RevenueSection data={current} />
        ) : section === "bookings" ? (
          <BookingsSection data={current} />
        ) : section === "guests" ? (
          <GuestsSection data={current} />
        ) : section === "conversion" ? (
          <ConversionSection data={current} />
        ) : (
          <CLVSection data={current} />
        )}
      </div>
    </div>
  );
}

/* ----------------------------- shared blocks ----------------------------- */

function Kpi({ label, value, sub, accent, testid }) {
  return (
    <div data-testid={testid} className={`surface rounded-md p-5 ${accent ? "border-[#D9A05B]/40" : ""}`}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-dim">{label}</div>
      <div className="font-display text-3xl font-light tracking-tighter text-white mt-2">{value}</div>
      {sub && <div className="text-[11px] text-dim mt-2">{sub}</div>}
    </div>
  );
}

function ChartBox({ title, sub, children, testid, className = "", height = 280 }) {
  return (
    <div className={`surface rounded-md p-6 ${className}`}>
      <h2 className="font-display text-base text-white">{title}</h2>
      {sub && <p className="text-xs text-dim mt-1">{sub}</p>}
      <div style={{ height }} className="mt-4" data-testid={testid}>{children}</div>
    </div>
  );
}

function EmptyMsg({ children = "No data for the selected filters." }) {
  return (
    <div className="surface rounded-md py-16 text-center text-sm text-dim" data-testid="empty-state">
      {children}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {[1,2,3,4,5,6].map((i) => (
        <div key={i} className="h-48 surface rounded animate-pulse" />
      ))}
    </div>
  );
}

const colourOf = (s) => SOURCE_COLORS[s] || "#6B7280";

/* ------------------------------- REVENUE -------------------------------- */

function RevenueSection({ data }) {
  if (!data) return <SkeletonGrid />;
  if (!data.total_revenue && !data.revenue_by_source?.length) return <EmptyMsg />;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi testid="kpi-total-revenue" label="Total revenue" value={fmtAUD(data.total_revenue)} sub="Gross of commission" accent />
        <Kpi testid="kpi-net-revenue" label="Net revenue" value={fmtAUD(data.net_revenue)} sub="After OTA commission" />
        <Kpi testid="kpi-commission" label="Commission paid" value={fmtAUD(data.total_commission)} sub="OTA platforms" />
        <Kpi
          testid="kpi-direct-pct"
          label="Direct share"
          value={fmtPct(data.split.direct / Math.max(1, data.split.direct + data.split.ota) * 100)}
          sub={`${fmtAUD(data.split.direct)} from direct`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title="Revenue by month — OTA vs Direct" sub="Stacked monthly view of channel mix" testid="chart-monthly-split">
          {data.monthly_split.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><BarChart data={data.monthly_split}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#8F95A3" }} />
              <Bar dataKey="direct" stackId="a" fill={CHANNEL_COLORS.Direct} name="Direct" />
              <Bar dataKey="ota" stackId="a" fill={CHANNEL_COLORS.OTA} name="OTA" />
            </BarChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="OTA vs Direct split" sub="Donut by gross revenue" testid="chart-ota-direct-donut">
          {(data.split.direct + data.split.ota) === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><PieChart>
              <Pie
                data={[{ name: "Direct", value: data.split.direct }, { name: "OTA", value: data.split.ota }].filter((d) => d.value > 0)}
                dataKey="value" nameKey="name" innerRadius={60} outerRadius={100} stroke="#090A0E" strokeWidth={3}
              >
                <Cell fill={CHANNEL_COLORS.Direct} />
                <Cell fill={CHANNEL_COLORS.OTA} />
              </Pie>
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
              <Legend wrapperStyle={{ fontSize: 12, color: "#8F95A3" }} />
            </PieChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Revenue by OTA platform" sub="Gross revenue per OTA" testid="chart-revenue-ota-platforms">
          {data.revenue_by_ota_platform.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><BarChart data={data.revenue_by_ota_platform} margin={{ bottom: 40 }}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="revenue" radius={[4, 4, 0, 0]}>
                {data.revenue_by_ota_platform.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
              </Bar>
            </BarChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Revenue by property" sub="Horizontal ranking" testid="chart-revenue-property" height={Math.max(280, data.revenue_by_property.length * 32 + 60)}>
          {data.revenue_by_property.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><BarChart data={data.revenue_by_property} layout="vertical" margin={{ left: 40 }}>
              <CartesianGrid stroke="#1c1f27" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#8F95A3", fontSize: 10 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <YAxis type="category" dataKey="property" tick={{ fill: "#8F95A3", fontSize: 11 }} width={130} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="revenue" fill="#D9A05B" radius={[0, 4, 4, 0]} />
            </BarChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Avg booking value by source" sub="Direct vs each OTA" testid="chart-avg-value-by-source">
          {data.avg_value_by_source.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><BarChart data={data.avg_value_by_source} margin={{ bottom: 40 }}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(1)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
              <Bar dataKey="avg" radius={[4, 4, 0, 0]}>
                {data.avg_value_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
              </Bar>
            </BarChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Commission cost by platform" sub="Estimated OTA fees" testid="chart-commission-by-platform">
          {data.commission_by_source.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><BarChart data={data.commission_by_source} margin={{ bottom: 40 }}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(1)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
              <Bar dataKey="commission" fill="#E05A50" radius={[4, 4, 0, 0]} />
            </BarChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Month-on-month revenue trend" sub="Total revenue per month" testid="chart-mom-trend" className="lg:col-span-2">
          {data.monthly_total.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><LineChart data={data.monthly_total}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
              <Line type="monotone" dataKey="revenue" stroke="#D9A05B" strokeWidth={2} dot={{ r: 3, fill: "#D9A05B" }} />
            </LineChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Revenue YoY comparison" sub="Current period vs prior year same months" testid="chart-yoy" className="lg:col-span-2">
          {data.monthly_with_py.length === 0 ? <EmptyMsg /> : (
            <ResponsiveContainer><LineChart data={data.monthly_with_py}>
              <CartesianGrid stroke="#1c1f27" vertical={false} />
              <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#8F95A3" }} />
              <Line type="monotone" name="Current year" dataKey="current_year" stroke="#D9A05B" strokeWidth={2} dot={false} />
              <Line type="monotone" name="Prior year" dataKey="prior_year" stroke="#4B6BF5" strokeWidth={2} dot={false} strokeDasharray="4 4" />
            </LineChart></ResponsiveContainer>
          )}
        </ChartBox>
      </div>
    </div>
  );
}

/* ------------------------------- BOOKINGS ------------------------------- */

function BookingsSection({ data }) {
  if (!data) return <SkeletonGrid />;
  if (data.total_bookings === 0) return <EmptyMsg />;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi testid="kpi-total-bookings" label="Total bookings" value={fmtNumber(data.total_bookings)} sub="In period" />
        <Kpi testid="kpi-unique-guests" label="Unique guests" value={fmtNumber(data.unique_guests)} sub="In period" />
        <Kpi label="Avg LOS (top source)" value={(data.avg_los_by_source[0]?.avg_nights ?? 0) + "n"} sub={data.avg_los_by_source[0]?.source || "—"} />
        <Kpi label="Avg lead time (top)" value={(data.avg_lead_by_source[0]?.avg_days ?? 0) + "d"} sub={data.avg_lead_by_source[0]?.source || "—"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title="Bookings by source" sub="Counts per channel" testid="chart-bookings-source">
          <ResponsiveContainer><BarChart data={data.bookings_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="bookings" radius={[4, 4, 0, 0]}>
              {data.bookings_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Bookings by property" sub="Volume per property" testid="chart-bookings-property">
          <ResponsiveContainer><BarChart data={data.bookings_by_property} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="property" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="bookings" fill="#D9A05B" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Occupancy trend by month" sub="Nights booked per month" testid="chart-occupancy">
          <ResponsiveContainer><LineChart data={data.occupancy_trend}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line type="monotone" dataKey="nights" stroke="#16B5C6" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Check-in day of week" sub="Which days guests arrive" testid="chart-dow">
          <ResponsiveContainer><BarChart data={data.checkin_by_dow}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="day" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="bookings" fill="#D9A05B" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Avg length of stay by source" sub="Mean nights per booking" testid="chart-avg-los">
          <ResponsiveContainer><BarChart data={data.avg_los_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v} nights`} />
            <Bar dataKey="avg_nights" radius={[4, 4, 0, 0]}>
              {data.avg_los_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Avg lead time by source" sub="Days from booking to check-in" testid="chart-avg-lead">
          <ResponsiveContainer><BarChart data={data.avg_lead_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v} days`} />
            <Bar dataKey="avg_days" radius={[4, 4, 0, 0]}>
              {data.avg_lead_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <div className="surface rounded-md p-6">
          <h2 className="font-display text-base text-white">Top 10 properties</h2>
          <p className="text-xs text-dim mt-1">Ranked by booking count</p>
          <div className="mt-4 space-y-2" data-testid="top-properties-list">
            {data.top_properties.map((p, i) => (
              <div key={p.property} className="flex items-center gap-3 text-sm">
                <span className="text-dim text-[10px] tabular-nums w-5">{i+1}</span>
                <span className="text-white flex-1 truncate">{p.property}</span>
                <span className="tabular-nums text-dim">{fmtNumber(p.bookings)}</span>
              </div>
            ))}
          </div>
        </div>

        <ChartBox title="Seasonal booking pattern" sub="Check-ins by month of year" testid="chart-seasonal">
          <ResponsiveContainer><BarChart data={data.seasonal_pattern}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="bookings" fill="#16B5C6" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>
      </div>
    </div>
  );
}

/* -------------------------------- GUESTS -------------------------------- */

function GuestsSection({ data }) {
  if (!data) return <SkeletonGrid />;
  if (data.total_unique_guests === 0) return <EmptyMsg />;

  const nvr = data.new_vs_returning || [];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi testid="kpi-unique-in-period" label="Unique guests" value={fmtNumber(data.total_unique_guests)} sub="In selected period" />
        <Kpi label="New guests" value={fmtNumber(nvr[0]?.value || 0)} sub="First stay in period" />
        <Kpi label="Returning guests" value={fmtNumber(nvr[1]?.value || 0)} sub="Stayed before" />
        <Kpi label="Top CLV (top guest)" value={fmtAUD(data.top_guests[0]?.lifetime_spend || 0)} sub={data.top_guests[0]?.name || "—"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title="New vs returning" sub="Acquisition mix in period" testid="chart-new-returning">
          {nvr.every((d) => d.value === 0) ? (
            <EmptyMsg />
          ) : (
            <ResponsiveContainer><PieChart>
              <Pie data={nvr.filter(d=>d.value>0)} dataKey="value" nameKey="name" innerRadius={60} outerRadius={100} stroke="#090A0E" strokeWidth={3}>
                <Cell fill="#D9A05B" />
                <Cell fill="#4B6BF5" />
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12, color: "#8F95A3" }} />
            </PieChart></ResponsiveContainer>
          )}
        </ChartBox>

        <ChartBox title="Repeat booking rate by source" sub="% of guests with 2+ stays" testid="chart-repeat-rate">
          <ResponsiveContainer><BarChart data={data.repeat_rate_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
            <Bar dataKey="rate" radius={[4, 4, 0, 0]}>
              {data.repeat_rate_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Guest segment distribution" sub="Count of guests in each segment" testid="chart-segment-dist" className="lg:col-span-2">
          <ResponsiveContainer><BarChart data={data.segment_distribution} margin={{ bottom: 70 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="segment" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-30} textAnchor="end" interval={0} height={80} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="guests" fill="#D9A05B" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Avg stays per guest by source" sub="Mean stays for guests of each source" testid="chart-avg-stays">
          <ResponsiveContainer><BarChart data={data.avg_stays_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="avg_stays" radius={[4, 4, 0, 0]}>
              {data.avg_stays_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Guests by number of stays" sub="Repeat-stay histogram" testid="chart-stays-histogram">
          <ResponsiveContainer><BarChart data={data.stays_histogram}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="bucket" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="guests" fill="#16B5C6" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Guest acquisition trend" sub="New guests per month" testid="chart-acquisition" className="lg:col-span-2">
          <ResponsiveContainer><LineChart data={data.acquisition_trend}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line type="monotone" dataKey="new_guests" stroke="#D9A05B" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart></ResponsiveContainer>
        </ChartBox>
      </div>

      <div className="surface rounded-md overflow-hidden">
        <div className="px-6 py-4 border-b divider">
          <h2 className="font-display text-base">Top 20 guests by lifetime spend</h2>
          <p className="text-xs text-dim mt-1">Click a guest to open their profile.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0E1015]">
              <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
                <th className="text-left px-4 py-3 font-semibold w-8">#</th>
                <th className="text-left px-4 py-3 font-semibold">Guest</th>
                <th className="text-left px-4 py-3 font-semibold">Most used source</th>
                <th className="text-right px-4 py-3 font-semibold">Stays</th>
                <th className="text-right px-4 py-3 font-semibold">Lifetime spend</th>
              </tr>
            </thead>
            <tbody data-testid="top-guests-table">
              {data.top_guests.map((g, i) => (
                <tr key={g.email} className="tbl-row">
                  <td className="px-4 py-3 text-dim tabular-nums">{i+1}</td>
                  <td className="px-4 py-3">
                    <Link to={`/guests/${encodeURIComponent(g.email)}`} className="text-white hover:underline">
                      {g.name}
                    </Link>
                    <div className="text-[11px] text-dim">{g.email}</div>
                  </td>
                  <td className="px-4 py-3 text-dim">{g.primary_source || "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fmtNumber(g.total_stays)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fmtAUD(g.lifetime_spend)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------ CONVERSION ------------------------------ */

function ConversionSection({ data }) {
  if (!data) return <SkeletonGrid />;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi
          testid="kpi-ota-direct-rate"
          label="OTA → Direct conversion"
          value={fmtPct(data.ota_to_direct_conversion_rate)}
          sub={`${data.ota_to_direct_converters} of ${data.ota_to_direct_converters + data.ota_only_guests} OTA guests`}
          accent
        />
        <Kpi
          testid="kpi-commission-saved"
          label="Commission saved (direct)"
          value={fmtAUD(data.commission_saved_from_direct)}
          sub={`Avg OTA rate ${data.avg_ota_rate_used}%`}
        />
        <Kpi
          testid="kpi-lost-revenue"
          label="Lost revenue (cancellations)"
          value={fmtAUD(data.lost_revenue)}
          sub="In selected period"
        />
        <Kpi
          label="High score guests"
          value={fmtNumber(data.score_bands.find(b=>b.band.startsWith("High"))?.guests || 0)}
          sub="Revenue opp ≥ 75"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title="Direct booking % trend" sub="Is your direct share growing?" testid="chart-direct-pct-trend">
          <ResponsiveContainer><LineChart data={data.direct_pct_trend}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
            <Line type="monotone" dataKey="direct_pct" stroke={CHANNEL_COLORS.Direct} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Top OTA conversion opportunity" sub="Avg direct conversion score by source" testid="chart-top-ota-opp">
          <ResponsiveContainer><BarChart data={data.top_ota_opportunity} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} domain={[0, 100]} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="avg_score" radius={[4, 4, 0, 0]}>
              {data.top_ota_opportunity.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Score bands" sub="Guests by revenue opportunity score" testid="chart-score-bands">
          <ResponsiveContainer><BarChart data={data.score_bands}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="band" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="guests" radius={[4, 4, 0, 0]}>
              {data.score_bands.map((d, i) => <Cell key={i} fill={d.color} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Cancellation rate by source" sub="% of bookings cancelled" testid="chart-cancel-rate-source">
          <ResponsiveContainer><BarChart data={data.cancel_rate_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
            <Bar dataKey="rate" radius={[4, 4, 0, 0]}>
              {data.cancel_rate_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Cancellation rate trend" sub="Monthly cancel rate over time" testid="chart-cancel-trend" className="lg:col-span-2">
          <ResponsiveContainer><LineChart data={data.cancel_trend}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
            <Line type="monotone" dataKey="rate" stroke="#E05A50" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart></ResponsiveContainer>
        </ChartBox>
      </div>
    </div>
  );
}

/* --------------------------------- CLV ---------------------------------- */

function CLVSection({ data }) {
  if (!data) return <SkeletonGrid />;
  if (!data.avg_clv) return <EmptyMsg />;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi testid="kpi-avg-clv" label="Average CLV" value={fmtAUD(data.avg_clv)} sub="Across all active guests" accent />
        <Kpi
          testid="kpi-top25-share"
          label="Top 25% revenue share"
          value={fmtPct(data.top25_share)}
          sub={`${fmtAUD(data.top25_revenue)} of ${fmtAUD(data.total_revenue)}`}
        />
        <Kpi
          label="Best source CLV"
          value={fmtAUD(data.avg_clv_by_source[0]?.avg_clv || 0)}
          sub={data.avg_clv_by_source[0]?.source || "—"}
        />
        <Kpi
          label="Cohorts tracked"
          value={fmtNumber(data.clv_by_acquisition_year.length)}
          sub="Acquisition years"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartBox title="Avg CLV by booking source" sub="Mean lifetime spend per source" testid="chart-clv-by-source">
          <ResponsiveContainer><BarChart data={data.avg_clv_by_source} margin={{ bottom: 40 }}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="source" tick={{ fill: "#8F95A3", fontSize: 10 }} angle={-25} textAnchor="end" interval={0} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(1)}k`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
            <Bar dataKey="avg_clv" radius={[4, 4, 0, 0]}>
              {data.avg_clv_by_source.map((d, i) => <Cell key={i} fill={colourOf(d.source)} />)}
            </Bar>
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="CLV distribution" sub="Histogram of guest lifetime value" testid="chart-clv-distribution">
          <ResponsiveContainer><BarChart data={data.clv_distribution}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="range" tick={{ fill: "#8F95A3", fontSize: 9 }} interval={0} angle={-15} textAnchor="end" height={50} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="guests" fill="#D9A05B" radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>
        </ChartBox>

        <ChartBox title="CLV by acquisition cohort" sub="Are recent cohorts worth more?" testid="chart-clv-cohorts" className="lg:col-span-2">
          <ResponsiveContainer><LineChart data={data.clv_by_acquisition_year}>
            <CartesianGrid stroke="#1c1f27" vertical={false} />
            <XAxis dataKey="year" tick={{ fill: "#8F95A3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#8F95A3", fontSize: 11 }} tickFormatter={(v) => `$${(v/1000).toFixed(1)}k`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => fmtAUD(v)} />
            <Line type="monotone" dataKey="avg_clv" stroke="#D9A05B" strokeWidth={2} dot={{ r: 4, fill: "#D9A05B" }} />
          </LineChart></ResponsiveContainer>
        </ChartBox>
      </div>
    </div>
  );
}
