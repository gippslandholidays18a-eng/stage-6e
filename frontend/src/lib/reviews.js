// Stage 6E — Review tracker constants + helpers.

export const REVIEW_SOURCES = [
  "Airbnb", "Booking.com", "Stayz", "VRBO", "Expedia",
  "Trip.com", "Direct", "Google", "Other",
];

export const REVIEW_CATEGORIES = [
  "Cleanliness", "Communication", "Location", "Value",
  "Accuracy", "Check-in", "Facilities",
];

export const SENTIMENTS = [
  { key: "Positive", color: "#5BD1A8" },
  { key: "Neutral",  color: "#D9A05B" },
  { key: "Negative", color: "#E05A50" },
];

export const findSentiment = (k) => SENTIMENTS.find((s) => s.key === k) || SENTIMENTS[1];

export const suggestSentiment = (rating) => {
  if (rating == null) return "Neutral";
  if (rating >= 5) return "Positive";
  if (rating >= 3) return "Neutral";
  return "Negative";
};

export const fmtReviewDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-AU", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch {
    return iso;
  }
};
