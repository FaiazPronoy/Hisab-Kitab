export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
export const KEY = process.env.NEXT_PUBLIC_API_KEY || "local-dev-key";

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", KEY);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(`${API}${path}`, { ...init, headers });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : j.detail?.message || JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const imageUrl = (docId: string, page: number) => `${API}/documents/${docId}/pages/${page}/image?api_key=${KEY}`;
export const eventsUrl = (docId: string) => `${API}/documents/${docId}/events?api_key=${KEY}`;

export type Doc = {
  id: string; filename: string; kind: string; status: string; page_count: number; pages_done: number;
  pages_failed: number; error_code: string | null; error_message: string | null; created_at: string;
  pages?: { page_no: number; status: string; source: string | null; reason: string | null; ocr_conf: number | null }[];
  invoices?: InvoiceSummary[];
};

export type InvoiceSummary = {
  id: string; document_id: string; status: string; invoice_number: string | null; invoice_date: string | null;
  supplier_name: string | null; currency: string | null; total: string | null; page_start: number | null;
  sheet_name: string | null; row_index: number | null; findings: Record<string, number>; filename?: string;
};

export type Field = {
  value: string | null; value_raw: string | null; confidence: number | null; page: number | null; line_id: string | null;
  bbox: number[] | null; quote: string | null; source: string | null; null_reason: string | null; verified: boolean;
};

export type Finding = { rule_code: string; severity: string; field: string | null; message: string; expected: string | null; actual: string | null };
