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
