import { useRef, useState } from "react";
import { api, fmtMoney } from "@/lib/api";
import { toast } from "sonner";
import { UploadCloud, FileText, CheckCircle2, AlertTriangle, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function Import() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const fileRef = useRef(null);
  const navigate = useNavigate();

  const handleFiles = async (f) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".csv")) {
      toast.error("Please upload a .csv file");
      return;
    }
    setFile(f);
    setLoading(true);
    setPreview(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await api.post("/import/preview", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPreview(r.data);
      if (r.data.mode === "profile_enrichment") {
        toast.success(`${r.data.platform} · ${r.data.valid_rows} guest profile${r.data.valid_rows === 1 ? "" : "s"} ready to enrich`);
      } else if (r.data.platform && r.data.platform !== "Generic") {
        toast.success(`${r.data.platform} · ${r.data.to_import_count ?? r.data.valid_rows} new, ${r.data.existing_count ?? 0} already exist`);
      } else if (r.data.missing_required?.length) {
        toast.warning(`Missing required columns: ${r.data.missing_required.join(", ")}`);
      } else {
        toast.success(`Parsed ${r.data.valid_rows} of ${r.data.total_rows} rows`);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not parse CSV");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview?.rows?.length) return;
    setConfirming(true);
    try {
      const r = await api.post("/import/confirm", {
        filename: preview.filename,
        rows: preview.rows,
        mode: preview.mode || "booking_import",
        platform: preview.platform || "",
      });
      const isEnrich = (preview.mode === "profile_enrichment");
      if (isEnrich) {
        toast.success(`Enriched ${r.data.inserted + r.data.updated} guest profiles · ${r.data.inserted} new, ${r.data.updated} updated`);
      } else {
        toast.success(`Imported ${r.data.successful_rows} new reservations` + (r.data.skipped_existing ? ` · ${r.data.skipped_existing} already existed` : ""));
      }
      reset();
      setTimeout(() => navigate(isEnrich ? "/segments" : "/reservations"), 400);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import failed");
    } finally {
      setConfirming(false);
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const previewRows = preview?.rows?.slice(0, 10) || [];

  return (
    <div data-testid="import-page" className="space-y-8 max-w-6xl">
      <header>
        <div className="text-[11px] uppercase tracking-[0.22em] text-dim">Import</div>
        <h1 className="font-display text-3xl tracking-tight mt-1">Upload booking CSV</h1>
        <p className="text-sm text-dim mt-2 max-w-2xl">
          Drop in any booking export. We&apos;ll detect columns, preview the first 10 rows, and classify each
          reservation by source on import. Multiple uploads append — no overwrites.
        </p>
      </header>

      {!file && (
        <div
          data-testid="upload-dropzone"
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            handleFiles(e.dataTransfer.files?.[0]);
          }}
          className="surface rounded-md py-20 px-6 flex flex-col items-center text-center cursor-pointer hover:bg-[#14161D] transition relative overflow-hidden"
        >
          <div
            className="absolute inset-0 opacity-[0.06] pointer-events-none"
            style={{
              backgroundImage:
                "url(https://images.unsplash.com/photo-1770486036751-e55247238964?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjY2NzN8MHwxfHNlYXJjaHwzfHxhYnN0cmFjdCUyMGRhdGElMjBncmlkJTIwZGFya3xlbnwwfHx8fDE3ODA3MDgxMTB8MA&ixlib=rb-4.1.0&q=85)",
              backgroundSize: "cover",
            }}
          />
          <div className="relative">
            <UploadCloud className="w-10 h-10 text-[#D9A05B] mx-auto" />
            <div className="font-display text-xl mt-4">Drop CSV here or click to browse</div>
            <p className="text-sm text-dim mt-2 max-w-md">
              We accept exports from Airbnb, Booking.com, Stayz, VRBO, Expedia, your PMS, or custom CSVs.
            </p>
            <button
              data-testid="upload-csv-button"
              type="button"
              className="mt-6 bg-brand text-black px-5 py-2.5 rounded-md text-sm font-medium hover:opacity-90"
            >
              Choose file
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              hidden
              data-testid="csv-file-input"
              onChange={(e) => handleFiles(e.target.files?.[0])}
            />
          </div>
        </div>
      )}

      {file && (
        <div className="space-y-6">
          <div className="surface rounded-md p-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-[#D9A05B]" />
              <div>
                <div className="text-sm font-medium" data-testid="selected-filename">{file.name}</div>
                <div className="text-xs text-dim">{(file.size / 1024).toFixed(1)} KB</div>
              </div>
            </div>
            <button
              data-testid="cancel-upload-button"
              onClick={reset}
              className="text-dim hover:text-white p-2"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {loading && <div className="text-sm text-dim">Parsing CSV…</div>}

          {preview && (
            <>
              <ValidationPanel preview={preview} />
              {preview.mode === "profile_enrichment" ? (
                <EnrichmentPreview preview={preview} previewRows={previewRows} />
              ) : (
                <BookingPreview preview={preview} previewRows={previewRows} />
              )}

              <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-end">
                <button
                  data-testid="cancel-import-button"
                  onClick={reset}
                  className="px-4 py-2.5 rounded-md text-sm border border-[#22252F] text-dim hover:text-white hover:bg-[#14161D]"
                >
                  Cancel
                </button>
                <button
                  data-testid="confirm-import-button"
                  disabled={confirming || !preview.valid_rows}
                  onClick={handleConfirm}
                  className="bg-brand text-black px-6 py-2.5 rounded-md text-sm font-medium disabled:opacity-40 hover:opacity-90"
                >
                  {confirming
                    ? "Importing…"
                    : preview.mode === "profile_enrichment"
                      ? `Confirm enrichment (${preview.valid_rows} guests)`
                      : `Confirm import (${preview.to_import_count ?? preview.valid_rows} new rows)`}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      <FieldHelp />
    </div>
  );
}

function ValidationPanel({ preview }) {
  const errors = preview.row_errors || [];
  const isEnrich = preview.mode === "profile_enrichment";
  const platform = preview.platform || "Generic";
  const platformOk = platform !== "Generic" || preview.valid_rows > 0;

  return (
    <div className="surface rounded-md p-5" data-testid="validation-panel">
      <div className="flex items-center gap-2">
        {platformOk ? (
          <CheckCircle2 className="w-4 h-4 text-[#419B72]" />
        ) : (
          <AlertTriangle className="w-4 h-4 text-[#E05A50]" />
        )}
        <span className="text-sm" data-testid="detected-platform">
          Detected platform: <span className="text-white font-medium">{platform}</span>
          {" · "}
          <span className="uppercase tracking-[0.18em] text-[10px] text-dim">
            {isEnrich ? "Guest Profile Enrichment" : "Booking Import"}
          </span>
        </span>
      </div>

      {isEnrich ? (
        <div className="mt-3 text-xs text-[#D9A05B] bg-[#D9A05B]/10 border border-[#D9A05B]/40 rounded-md px-3 py-2" data-testid="enrichment-banner">
          This file will enrich existing guest profiles only. No reservation records will be created.
          {preview.matched_by_email != null && (
            <span className="block text-dim mt-1">
              {preview.valid_rows} profile{preview.valid_rows === 1 ? "" : "s"} in file · {preview.matched_by_email} already match an existing guest by email.
            </span>
          )}
        </div>
      ) : (
        <div className="mt-3 text-xs text-dim" data-testid="booking-banner">
          {preview.valid_rows} reservation{preview.valid_rows === 1 ? "" : "s"} detected from {platform}.
          {preview.to_import_count != null && (
            <> {preview.to_import_count} will be imported, {preview.existing_count ?? 0} already exist and will be skipped.</>
          )}
        </div>
      )}

      {errors.length > 0 && (
        <div className="mt-3 text-xs text-dim">
          {errors.length} rows skipped (showing first 5):{" "}
          {errors.slice(0, 5).map((e, i) => (
            <span key={i} className="font-mono mr-3">
              row {e.row}: {e.error}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function BookingPreview({ preview, previewRows }) {
  return (
    <div className="surface rounded-md p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-lg">Preview · first 10 rows</h2>
          <p className="text-xs text-dim mt-1">
            {preview.valid_rows} of {preview.total_rows} rows ready to import
          </p>
        </div>
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
              <th className="text-left pb-3 pr-4 font-semibold">Reservation</th>
              <th className="text-left pb-3 pr-4 font-semibold">Guest</th>
              <th className="text-left pb-3 pr-4 font-semibold">Property</th>
              <th className="text-left pb-3 pr-4 font-semibold">Check-in</th>
              <th className="text-left pb-3 pr-4 font-semibold">Nights</th>
              <th className="text-right pb-3 pr-4 font-semibold">Value</th>
              <th className="text-left pb-3 pr-4 font-semibold">Raw source</th>
              <th className="text-left pb-3 font-semibold">Cancelled</th>
            </tr>
          </thead>
          <tbody data-testid="preview-table-body">
            {previewRows.map((r, i) => (
              <tr key={i} className="tbl-row">
                <td className="py-2.5 pr-4 font-mono text-[11px] text-dim">{r.reservation_id}</td>
                <td className="py-2.5 pr-4">
                  {r.guest_first_name} {r.guest_last_name}
                </td>
                <td className="py-2.5 pr-4 text-dim">{r.property_name || "—"}</td>
                <td className="py-2.5 pr-4 text-dim">{r.checkin_date || "—"}</td>
                <td className="py-2.5 pr-4 text-dim">{r.nights ?? "—"}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums">
                  {r.booking_value == null ? "—" : fmtMoney(r.booking_value)}
                </td>
                <td className="py-2.5 pr-4 text-dim">{r.raw_booking_source || "—"}</td>
                <td className="py-2.5 text-dim">{r.is_cancelled ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EnrichmentPreview({ preview, previewRows }) {
  return (
    <div className="surface rounded-md p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-lg">Preview · first 10 profiles</h2>
          <p className="text-xs text-dim mt-1">
            {preview.valid_rows} of {preview.total_rows} guest profiles ready to enrich
          </p>
        </div>
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.15em] text-[#6B7280]">
              <th className="text-left pb-3 pr-4 font-semibold">Guest</th>
              <th className="text-left pb-3 pr-4 font-semibold">Email</th>
              <th className="text-left pb-3 pr-4 font-semibold">Phone</th>
              <th className="text-left pb-3 pr-4 font-semibold">City</th>
              <th className="text-left pb-3 pr-4 font-semibold">Country</th>
              <th className="text-right pb-3 pr-4 font-semibold">Total bookings</th>
              <th className="text-right pb-3 font-semibold">Lifetime spend</th>
            </tr>
          </thead>
          <tbody data-testid="preview-enrichment-body">
            {previewRows.map((r, i) => (
              <tr key={i} className="tbl-row">
                <td className="py-2.5 pr-4">
                  {r.guest_first_name} {r.guest_last_name}
                </td>
                <td className="py-2.5 pr-4 text-dim font-mono text-[11px]">{r.guest_email || "—"}</td>
                <td className="py-2.5 pr-4 text-dim">{r.phone || "—"}</td>
                <td className="py-2.5 pr-4 text-dim">{r.city || "—"}</td>
                <td className="py-2.5 pr-4 text-dim">{r.country || "—"}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-dim">
                  {r.total_bookings_reported ?? "—"}
                </td>
                <td className="py-2.5 text-right tabular-nums">
                  {r.lifetime_spend_reported == null ? "—" : fmtMoney(r.lifetime_spend_reported)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FieldHelp() {
  const fields = [
    ["reservation_id", "Booking reference / reservation ID (required, unique)"],
    ["guest_first_name + guest_last_name", "Guest name"],
    ["guest_email", "Guest email address"],
    ["property_name", "Property / listing name"],
    ["checkin_date + checkout_date", "Stay dates (any common format)"],
    ["nights", "Auto-computed if omitted"],
    ["guest_count", "Number of guests"],
    ["booking_value", "Total gross value"],
    ["booking_source", "Raw channel — Airbnb, Booking.com, Direct, etc."],
    ["booking_date", "Date the booking was made"],
    ["is_cancelled", "yes/no, true/false, 1/0"],
  ];
  return (
    <details className="surface rounded-md p-5" data-testid="csv-help">
      <summary className="text-sm cursor-pointer text-white">Accepted column names</summary>
      <p className="text-xs text-dim mt-3">
        Column headers are matched case-insensitively. Common aliases are auto-detected.
      </p>
      <ul className="mt-3 grid sm:grid-cols-2 gap-2 text-xs">
        {fields.map(([k, v]) => (
          <li key={k} className="flex gap-2">
            <span className="font-mono text-[#D9A05B]">{k}</span>
            <span className="text-dim">— {v}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
