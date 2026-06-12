// Stage 6D — Inventory tracker helpers.

export const INV_CATEGORIES = [
  { key: "linens",      label: "Linens",       color: "#7AB8FF" },
  { key: "toiletries",  label: "Toiletries",   color: "#B486E0" },
  { key: "kitchen",     label: "Kitchen",      color: "#D9A05B" },
  { key: "cleaning",    label: "Cleaning",     color: "#5BD1A8" },
  { key: "electrical",  label: "Electrical",   color: "#E0904E" },
  { key: "first_aid",   label: "First aid",    color: "#E05A50" },
  { key: "decor",       label: "Decor",        color: "#8F95A3" },
];

export const INV_STATUSES = [
  { key: "ok",            label: "On target",   color: "#5BD1A8" },
  { key: "below_target",  label: "Below target", color: "#D9A05B" },
  { key: "low",           label: "Low stock",   color: "#E0904E" },
  { key: "out",           label: "Out of stock",color: "#E05A50" },
  { key: "inactive",      label: "Inactive",    color: "#5B606B" },
];

export const findInvCat = (k) => INV_CATEGORIES.find((c) => c.key === k) || INV_CATEGORIES[6];
export const findInvStatus = (k) => INV_STATUSES.find((s) => s.key === k) || INV_STATUSES[0];

export const fmtCount = (item) => {
  const u = item.unit && item.unit !== "each" ? ` ${item.unit}${item.current_count === 1 ? "" : "s"}` : "";
  return `${item.current_count}${u}`;
};
