// The shapes of Sift's JSON answers that React components read (gui.py).
export interface HealthCheck { key: string; label: string; rule: string; passed: boolean | null }
export interface Health {
  fiscal_year: number | null;
  excluded_reason: string | null;
  f_score: number | null;
  f_checks: number | null;
  f_level: "STRONG" | "MIDDLING" | "WEAK" | "NOT_ENOUGH" | null;
  f_words: string | null;
  f_detail: HealthCheck[];
  z_score: number | null;
  z_zone: "SAFE" | "GREY" | "DISTRESS" | null;
  z_words: string | null;
  z_meaning: string | null;
  z_parts: Record<string, number | null>;
}
