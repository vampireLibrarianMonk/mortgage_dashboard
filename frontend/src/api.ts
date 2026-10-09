import type {
  CalculateRequest,
  CalculateResponse,
  DocStage,
  HouseholdReconciliation,
  TaxDocument,
  TaxFact,
  TaxFormType,
} from "./types";

// In dev, Vite proxies /calculate and /profiles to the backend (see vite.config.ts).
// In production, FastAPI serves this built app, so same-origin relative paths work
// directly and through the Caddy reverse proxy (app.mortgage-dashboard).
// Override with VITE_API_BASE at build time if the API is hosted elsewhere.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function calculateMortgage(req: CalculateRequest): Promise<CalculateResponse> {
  const res = await fetch(`${API_BASE}/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

export interface ProfileSummary {
  id: string;
  address: string;
  updated_at: string;
}

export async function saveProfile(address: string, data: CalculateRequest): Promise<ProfileSummary> {
  const res = await fetch(`${API_BASE}/profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ address, data }),
  });
  if (!res.ok) throw new Error(`Save failed: ${res.status}`);
  return res.json();
}

export async function listProfiles(): Promise<ProfileSummary[]> {
  const res = await fetch(`${API_BASE}/profiles`);
  if (!res.ok) throw new Error(`Load failed: ${res.status}`);
  return res.json();
}

export async function loadProfile(id: string): Promise<{ address: string; data: CalculateRequest }> {
  const res = await fetch(`${API_BASE}/profiles/${id}`);
  if (!res.ok) throw new Error(`Load failed: ${res.status}`);
  return res.json();
}

export async function deleteProfile(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/profiles/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

// --- Plaid (read-only bank sync) ---

export interface ActualsCategoryTotals {
  Mortgage: number;
  Household: number;
  Utilities: number;
  Vehicle: number;
  ChildCare: number;
  PetCare: number;
  Discretionary: number;
}

export interface ActualsMonth {
  month: string; // "2026-06"
  categories: ActualsCategoryTotals;
  unbudgeted_outflow: number;
}

export interface ActualsYear {
  year: string;
  categories: ActualsCategoryTotals;
  unbudgeted_outflow: number;
}

export interface InitialHouseRepairItem {
  date: string; // "YYYY-MM-DD"
  name: string;
  amount: number;
  label: string;
}

// One-time move-in capital repairs: excluded from the budget, tracked with their
// own running grand total + line items (grows as older records are backfilled).
export interface InitialHouseRepair {
  total: number;
  by_year: Record<string, number>;
  items: InitialHouseRepairItem[];
  count: number;
}

export interface PlaidActuals {
  available: boolean;
  months: ActualsMonth[];
  years: ActualsYear[];
  // Optional for back-compat with actuals JSON generated before this field.
  // When plaidActuals is called with a profileId, this is scoped to that
  // property (an empty skeleton when it has no repairs yet).
  initial_house_repair?: InitialHouseRepair;
  // Per-property repair ledgers, keyed by profile_id (plus an "unassigned"
  // bucket for untagged legacy rows).
  initial_house_repair_by_profile?: Record<string, InitialHouseRepair>;
}

// Budget vs Actual reads the aggregates-only JSON the console `summary` command
// produces. When `profileId` is given, the initial_house_repair block is scoped
// to that property (empty skeleton if it has none yet); otherwise it's the
// global grand total. All other Plaid interaction is driven from the console.
export async function plaidActuals(profileId?: string | null): Promise<PlaidActuals> {
  const url = profileId
    ? `${API_BASE}/plaid/actuals?profile=${encodeURIComponent(profileId)}`
    : `${API_BASE}/plaid/actuals`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Actuals failed: ${res.status}`);
  return res.json();
}

// --- Categorization console ---

export async function runConsole(command: string): Promise<string[]> {
  const res = await fetch(`${API_BASE}/console/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!res.ok) throw new Error(`Console failed: ${res.status}`);
  const data = await res.json();
  return (data.output ?? []) as string[];
}

// --- Statement import (upload a PayPal statement zip/pdf) ---

export interface ImportPreviewFile {
  filename: string;
  reader: string | null;
  count: number;
  error: string | null;
}

export interface ImportPreviewRow {
  date: string;
  amount: number;
  name: string;
  category: string | null;
}

export interface ImportReconcileRow {
  date: string;
  amount: number;
  name: string;
}

export interface ImportPreview {
  files: ImportPreviewFile[];
  problems: string[];
  import_count: number;
  data_start: string;
  to_import: ImportPreviewRow[];
  pre_start_count: number;
  offsets_count: number;
  reconciled: ImportReconcileRow[];
}

export interface ImportResult {
  ok: boolean;
  error?: string;
  preview?: ImportPreview;
  summary?: string[];
}

async function postStatement(path: string, file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/console${path}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
}

export function previewStatement(file: File): Promise<ImportResult> {
  return postStatement("/import/preview", file);
}

export function commitStatement(file: File): Promise<ImportResult> {
  return postStatement("/import/commit", file);
}

// --- Order-details split (upload a Walmart/Amazon "Order details" PDF) ---

export interface OrderMatchedTxn {
  transaction_id: string;
  date: string | null;
  amount: number | null;
  name: string | null;
}

export interface OrderSplitChild {
  amount: number;
  category: string;
  note: string;
}

export interface OrderPlan {
  vendor: string;
  order_no: string | null;
  date: string | null;
  total: number | null;
  status: string; // ready | needs-confirm | no-match | ambiguous | no-total
  warnings: string[];
  matched: OrderMatchedTxn | null;
  children: OrderSplitChild[];
  candidates: OrderMatchedTxn[];
}

export interface OrderResult {
  ok: boolean;
  error?: string;
  plan?: OrderPlan;
  summary?: string[];
}

async function postOrder(path: string, file: File): Promise<OrderResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/console${path}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Order import failed: ${res.status}`);
  return res.json();
}

export function previewOrder(file: File): Promise<OrderResult> {
  return postOrder("/orders/preview", file);
}

export function commitOrder(file: File): Promise<OrderResult> {
  return postOrder("/orders/commit", file);
}

// --- Plaid: connect additional banks (link flow) ---

export interface PlaidStatus {
  configured: boolean;
  env: string;
}

export interface PlaidItem {
  slug: string;
  name: string;
}

export async function plaidStatus(): Promise<PlaidStatus> {
  const res = await fetch(`${API_BASE}/plaid/status`);
  if (!res.ok) throw new Error(`Plaid status failed: ${res.status}`);
  return res.json();
}

export async function plaidItems(): Promise<PlaidItem[]> {
  const res = await fetch(`${API_BASE}/plaid/items`);
  if (!res.ok) throw new Error(`Plaid items failed: ${res.status}`);
  const data = await res.json();
  return (data.items ?? data ?? []) as PlaidItem[];
}

export async function createLinkToken(): Promise<string> {
  const res = await fetch(`${API_BASE}/plaid/link-token`, { method: "POST" });
  if (!res.ok) throw new Error(`link-token failed: ${res.status}`);
  const data = await res.json();
  return data.link_token as string;
}

export async function exchangePublicToken(publicToken: string, name: string): Promise<PlaidItem> {
  const res = await fetch(`${API_BASE}/plaid/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ public_token: publicToken, name }),
  });
  if (!res.ok) throw new Error(`exchange failed: ${res.status}`);
  return res.json();
}

// --- System refresh (manual health check; replaces recurring pop-ups) ---

export interface SystemRefreshResult {
  ok: boolean;
  output: string[];
}

// Runs deploy/health-check.ps1 once on demand: relaunches the proxy / sibling
// app if they're down and returns the check's output lines.
export async function systemRefresh(): Promise<SystemRefreshResult> {
  const res = await fetch(`${API_BASE}/system/refresh`, { method: "POST" });
  if (!res.ok) throw new Error(`system refresh failed: ${res.status}`);
  return res.json();
}

// --- Balance snapshots (Timeline Builder funding dropdown) ---

export interface BalanceSnapshotAccount {
  key: string; // "<bank>:<mask>"
  bank: string | null;
  mask: string | null;
  name: string;
  balance: number | null;
  as_of: string | null;
}

// Read the persisted latest-balance snapshots (no Plaid hit).
export async function balancesSnapshot(): Promise<BalanceSnapshotAccount[]> {
  const res = await fetch(`${API_BASE}/plaid/balances-snapshot`);
  if (!res.ok) throw new Error(`balances-snapshot failed: ${res.status}`);
  const data = await res.json();
  return (data.accounts ?? []) as BalanceSnapshotAccount[];
}

// Live-pull every linked item's balances, overwrite the stored snapshots,
// and return the refreshed list.
export async function balancesRefresh(): Promise<BalanceSnapshotAccount[]> {
  const res = await fetch(`${API_BASE}/plaid/balances-refresh`, { method: "POST" });
  if (!res.ok) throw new Error(`balances-refresh failed: ${res.status}`);
  const data = await res.json();
  return (data.accounts ?? []) as BalanceSnapshotAccount[];
}

// --- Tax Prep (Phase 1: document foundation — upload/list/view/delete) ---

export interface TaxUploadResult {
  ok: boolean;
  created?: boolean;
  document?: TaxDocument;
  error?: string;
}

export interface TaxPreviewResult {
  ok: boolean;
  filename?: string;
  kind?: string;
  size_bytes?: number;
  id?: string;
  duplicate?: boolean;
  error?: string;
}

export async function taxListDocuments(year: number): Promise<TaxDocument[]> {
  const res = await fetch(`${API_BASE}/tax/${year}/documents`);
  if (!res.ok) throw new Error(`tax list failed: ${res.status}`);
  const data = await res.json();
  return (data.documents ?? []) as TaxDocument[];
}

export async function taxPreviewDocument(year: number, file: File): Promise<TaxPreviewResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/tax/${year}/documents/preview`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`tax preview failed: ${res.status}`);
  return res.json();
}

export async function taxUploadDocument(year: number, file: File): Promise<TaxUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/tax/${year}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`tax upload failed: ${res.status}`);
  return res.json();
}

export async function taxDeleteDocument(year: number, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/tax/${year}/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`tax delete failed: ${res.status}`);
}

// URL for the in-app viewer (original bytes, inline). Not fetched here — passed
// to an <img>/<iframe> src.
export function taxDocumentRawUrl(year: number, id: string): string {
  return `${API_BASE}/tax/${year}/documents/${id}/raw`;
}

// --- Phase 2: extraction + review ---

export type ExtractionProvider = "local" | "aws";

export interface TaxExtractResult {
  ok: boolean;
  provider?: ExtractionProvider;
  form_type?: TaxFormType;
  stage?: DocStage;
  fact_count?: number;
  facts?: TaxFact[];
  note?: string;
  error?: string;
}

// Run extraction on a stored document. provider 'local' is offline/free (little
// on scans); 'aws' uses Textract (opt-in). The backend classifies by content
// and, for a W-2, maps its boxes into facts.
export async function taxExtract(
  year: number,
  id: string,
  provider: ExtractionProvider,
): Promise<TaxExtractResult> {
  const res = await fetch(`${API_BASE}/tax/${year}/documents/${id}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
  if (!res.ok) throw new Error(`tax extract failed: ${res.status}`);
  return res.json();
}

export async function taxFacts(year: number, id: string): Promise<TaxFact[]> {
  const res = await fetch(`${API_BASE}/tax/${year}/documents/${id}/facts`);
  if (!res.ok) throw new Error(`tax facts failed: ${res.status}`);
  const data = await res.json();
  return (data.facts ?? []) as TaxFact[];
}

// Accept (value omitted/null) or correct (value provided) one fact. The backend
// preserves the original extracted_value and records an audit trail.
export async function taxVerifyFact(
  year: number,
  id: string,
  fieldCode: string,
  value: boolean | string | number | null,
): Promise<TaxFact | null> {
  const res = await fetch(
    `${API_BASE}/tax/${year}/documents/${id}/facts/${fieldCode}/verify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    },
  );
  if (!res.ok) throw new Error(`tax verify failed: ${res.status}`);
  const data = await res.json();
  return (data.fact ?? null) as TaxFact | null;
}

// --- Phase 3: household W-2 ↔ paystub reconciliation ---

export interface TaxReconcileResult {
  ok: boolean;
  reconciliation: HouseholdReconciliation | null;
  note?: string;
}

// Reconcile the whole household for a year: each person's W-2 cross-checked
// against their paystub-rebuilt totals, plus a household W-2 rollup. Computed
// on demand from already-extracted documents.
export async function taxReconcile(year: number): Promise<TaxReconcileResult> {
  const res = await fetch(`${API_BASE}/tax/${year}/reconcile`);
  if (!res.ok) throw new Error(`tax reconcile failed: ${res.status}`);
  return res.json();
}
