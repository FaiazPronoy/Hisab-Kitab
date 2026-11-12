"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Lang = "en" | "bn";
const KEY = "docintel.lang";

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (en: string, bn: string) => string };
const LangCtx = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (en) => en });

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => {
    try {
      if (localStorage.getItem(KEY) === "bn") setLangState("bn");
    } catch {}
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(KEY, l); } catch {}
  }, []);
  const t = useCallback((en: string, bn: string) => (lang === "bn" ? bn : en), [lang]);
  return <LangCtx.Provider value={{ lang, setLang, t }}>{children}</LangCtx.Provider>;
}

export const useLang = () => useContext(LangCtx);

// Bangla digits for counts shown in running text; money and ids stay as printed
const BN = "০১২৩৪৫৬৭৮৯";
export const bnNum = (v: number | string, lang: Lang) => (lang === "bn" ? String(v).replace(/\d/g, (d) => BN[+d]) : String(v));

const STATUS: Record<string, [string, string]> = {
  done: ["done", "সম্পন্ন"], needs_review: ["needs review", "রিভিউ দরকার"], approved: ["approved", "অনুমোদিত"],
  auto_validated: ["passed checks", "যাচাই পাস"], failed: ["failed", "ব্যর্থ"], queued: ["waiting", "অপেক্ষায়"],
  processing: ["reading", "পড়া চলছে"], finalizing: ["finishing", "শেষ হচ্ছে"], completed_with_errors: ["partly read", "আংশিক পড়া"],
  rejected: ["rejected", "বাতিল"], ledger: ["ledger row", "লেজার সারি"], po: ["purchase order", "ক্রয় আদেশ"],
  matched: ["matched", "মিলেছে"], error: ["error", "ত্রুটি"], warning: ["warning", "সতর্কতা"], critical: ["critical", "গুরুতর"],
  info: ["info", "তথ্য"], pending: ["pending", "বাকি"], extracted: ["read", "পড়া হয়েছে"],
};
export function statusLabel(value: string, lang: Lang) {
  const parts = value.split(" ");
  const last = parts.pop() || "";
  const hit = STATUS[last];
  if (!hit) return value.replaceAll("_", " ");
  const word = lang === "bn" ? hit[1] : hit[0];
  return parts.length ? `${bnNum(parts.join(" "), lang)} ${word}` : word;
}

const FIELDS: Record<string, [string, string]> = {
  invoice_number: ["Invoice number", "ইনভয়েস নম্বর"], invoice_date: ["Invoice date", "ইনভয়েসের তারিখ"], due_date: ["Due date", "শেষ তারিখ"],
  supplier_name: ["Supplier", "সরবরাহকারী"], customer_name: ["Customer", "ক্রেতা"], po_number: ["PO number", "ক্রয় আদেশ নম্বর"],
  currency: ["Currency", "মুদ্রা"], subtotal: ["Subtotal", "উপমোট"], discount: ["Discount", "ছাড়"], shipping: ["Shipping", "পরিবহন"],
  tax: ["Tax", "ট্যাক্স"], total: ["Total", "মোট"], bank_account: ["Bank account", "ব্যাংক অ্যাকাউন্ট"], status: ["Status", "অবস্থা"],
  payment: ["Payment", "পেমেন্ট"],
};
export function fieldLabel(k: string, lang: Lang) {
  const f = FIELDS[k];
  if (f) return lang === "bn" ? f[1] : f[0];
  const m = k.match(/^line_items\[(\d+)\]\.(\w+)$/);
  if (m) return lang === "bn" ? `লাইন ${+m[1] + 1}: ${m[2].replace("_", " ")}` : `Line ${+m[1] + 1}: ${m[2].replace("_", " ")}`;
  return k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " ");
}

// Bangla text for each check; English comes from the API as it is
const RULES_BN: Record<string, string> = {
  REQ_MISSING: "একটি দরকারি ঘর পাওয়া যায়নি।", OPT_MISSING: "এই ঘরটি ইনভয়েসে নেই।",
  GROUNDING_FAILED: "মানটি পাতায় পাওয়া যায়নি, তাই বাদ দেওয়া হয়েছে।", LINE_MATH: "পরিমাণ × দাম লাইনের মোটের সাথে মেলেনি।",
  SUBTOTAL_SUM: "লাইনগুলোর যোগফল উপমোটের সাথে মেলেনি।", TOTAL_MATH: "উপমোট, ছাড়, পরিবহন আর ট্যাক্সের যোগফল মোটের সাথে মেলেনি।",
  TAX_INCLUSIVE: "দামে হয়তো আগে থেকেই ট্যাক্স ধরা আছে।", TAX_LINES: "ট্যাক্সের লাইনগুলোর যোগফল মেলেনি।",
  TAX_RATE: "ট্যাক্সের হার অস্বাভাবিক।", AMOUNT_SANITY: "মোট শূন্য, ঋণাত্মক বা অস্বাভাবিক বড়।",
  DATE_SANITY: "তারিখটি ঠিক মনে হচ্ছে না।", CURRENCY: "শুধু $ চিহ্ন আছে, তাই USD ধরা হয়েছে।",
  LOW_CONFIDENCE: "এই মানটি নিয়ে সিস্টেম নিশ্চিত নয়।", SUSPICIOUS_CONTENT: "ডকুমেন্টে নির্দেশের মতো লেখা আছে। হাতে দেখুন।",
  EXTRACTION_FAILED: "মডেল কোনো কাজের উত্তর দেয়নি।", LONG_SEGMENT: "ইনভয়েসটি অনেক পাতার।",
  DUP_INVOICE: "আরেকটি ইনভয়েসের সাথে সরবরাহকারী, নম্বর আর মোট একই।", DUP_CONFLICT: "একই নম্বরের আরেকটি ইনভয়েস আছে, কিন্তু মোট আলাদা।",
  DUP_SUSPECTED: "আরেকটি ইনভয়েসের প্রায় কপি মনে হচ্ছে।",
  BANK_CHANGED: "এই সরবরাহকারীর আগের ইনভয়েসের থেকে ব্যাংক তথ্য আলাদা। পেমেন্টের আগে সরবরাহকারীকে ফোন করে নিশ্চিত হোন।",
  AMOUNT_OUTLIER: "এই সরবরাহকারীর সাধারণ ইনভয়েসের চেয়ে অনেক বড়।", CURRENCY_CHANGED: "এই সরবরাহকারী আগে সবসময় অন্য মুদ্রায় বিল করেছে।",
  NEW_SUPPLIER: "এই সরবরাহকারীর প্রথম ইনভয়েস, মিলিয়ে দেখার মতো আগের কিছু নেই।",
  PO_UNKNOWN: "ইনভয়েসের ক্রয় আদেশটি আপলোড করা তালিকায় নেই।", PO_SUPPLIER: "ক্রয় আদেশটি অন্য সরবরাহকারীর।",
  PO_CURRENCY: "ক্রয় আদেশটি অন্য মুদ্রায়।", PO_OVER: "এই ক্রয় আদেশের সব ইনভয়েস মিলিয়ে অনুমোদিত টাকার চেয়ে বেশি।",
};
export const ruleText = (code: string, en: string, lang: Lang) => (lang === "bn" && RULES_BN[code]) || en;

const ERRORS_BN: [RegExp, string][] = [
  [/New bank details need an approver/, "নতুন ব্যাংক তথ্যে অনুমোদনকারী লাগবে, সরবরাহকারীকে ফোন করার পর।"],
  [/need an approver/, "এত বড় ইনভয়েসে অনুমোদনকারী লাগবে।"],
  [/someone else has to approve/, "আপনি এই ইনভয়েসের টাকা বা প্রাপক বদলেছেন, তাই অন্য কাউকে অনুমোদন করতে হবে।"],
  [/changed by someone else|changed concurrently/, "অন্য কেউ এর মধ্যে ইনভয়েসটি বদলেছেন। পাতা আবার লোড করুন।"],
  [/already in a payment file/, "ইনভয়েসটি পেমেন্ট ফাইলে আছে, আর বদলানো যাবে না।"],
  [/Already approved/, "ইতিমধ্যে অনুমোদিত।"],
  [/Sign in/, "বদল বা অনুমোদন করতে সাইন ইন করুন।"],
];
export function errorText(msg: string, lang: Lang) {
  if (lang !== "bn") return msg;
  const hit = ERRORS_BN.find(([re]) => re.test(msg));
  return hit ? hit[1] : msg;
}
