import type { CalculateRequest, CalculateResponse } from "./types";

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

export interface PlaidActuals {
  available: boolean;
  months: ActualsMonth[];
  years: ActualsYear[];
}

// Budget vs Actual reads the aggregates-only JSON the console `summary` command
// produces. All other Plaid interaction (status, sync, balances, link diagnostics)
// is driven from the console page, not the dashboard.
export async function plaidActuals(): Promise<PlaidActuals> {
  const res = await fetch(`${API_BASE}/plaid/actuals`);
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
