import { useEffect, useState } from "react";
import {
  plaidStatus,
  plaidItems,
  createLinkToken,
  exchangePublicToken,
  type PlaidItem,
} from "../api";

// Plaid Link is loaded from Plaid's official CDN on demand (no npm dependency).
// This is the same script the react-plaid-link wrapper uses under the hood.
const PLAID_SCRIPT = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";

interface PlaidHandler {
  open: () => void;
  exit: () => void;
}
interface PlaidLinkGlobal {
  create: (config: {
    token: string;
    onSuccess: (publicToken: string, metadata: unknown) => void;
    onExit: (err: unknown) => void;
  }) => PlaidHandler;
}
declare global {
  interface Window {
    Plaid?: PlaidLinkGlobal;
  }
}

function loadPlaidScript(): Promise<PlaidLinkGlobal> {
  return new Promise((resolve, reject) => {
    if (window.Plaid) {
      resolve(window.Plaid);
      return;
    }
    const existing = document.querySelector(`script[src="${PLAID_SCRIPT}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve(window.Plaid!));
      existing.addEventListener("error", () => reject(new Error("Plaid script failed to load")));
      return;
    }
    const s = document.createElement("script");
    s.src = PLAID_SCRIPT;
    s.async = true;
    s.onload = () => (window.Plaid ? resolve(window.Plaid) : reject(new Error("Plaid unavailable after load")));
    s.onerror = () => reject(new Error("Plaid script failed to load"));
    document.body.appendChild(s);
  });
}

export default function BankManager() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [env, setEnv] = useState("");
  const [items, setItems] = useState<PlaidItem[]>([]);
  const [bankName, setBankName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const [st, its] = await Promise.all([plaidStatus(), plaidItems()]);
      setConfigured(st.configured);
      setEnv(st.env);
      setItems(its);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function connect() {
    setErr(null);
    setMsg(null);
    const name = bankName.trim();
    if (!name) {
      setErr("Enter a name for the bank first (e.g. Chase).");
      return;
    }
    setBusy(true);
    try {
      const Plaid = await loadPlaidScript();
      const token = await createLinkToken();
      const handler = Plaid.create({
        token,
        onSuccess: async (publicToken: string) => {
          try {
            const item = await exchangePublicToken(publicToken, name);
            setMsg(`Connected ${item.name}. Run \`sync\` in the Console to pull its transactions.`);
            setBankName("");
            void refresh();
          } catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        },
        onExit: (exitErr: unknown) => {
          setBusy(false);
          if (exitErr) setErr(typeof exitErr === "string" ? exitErr : "Link cancelled or failed.");
        },
      });
      handler.open();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="bank-manager">
      <h2>Connected banks</h2>

      {configured === false && (
        <p className="error">
          Plaid is not configured (PLAID_CLIENT_ID / PLAID_SECRET missing). Set those on the
          server before connecting a bank.
        </p>
      )}
      {configured && (
        <p className="bank-env">Plaid environment: <strong>{env}</strong></p>
      )}

      {items.length > 0 ? (
        <ul className="bank-list">
          {items.map((it) => (
            <li key={it.slug}>
              <span className="bank-name">{it.name}</span>
              <span className="bank-slug">{it.slug}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="bank-empty">No banks connected yet.</p>
      )}

      <div className="bank-connect">
        <h3>Connect a new bank</h3>
        <p className="bank-hint">
          Add another institution (e.g. your Chase Prime Visa) so its transactions sync in.
          You'll log in through Plaid's secure window; credentials never touch this app.
        </p>
        <div className="bank-connect-row">
          <input
            type="text"
            className="bank-input"
            placeholder="Bank name (e.g. Chase)"
            value={bankName}
            disabled={busy || !configured}
            onChange={(e) => setBankName(e.target.value)}
          />
          <button
            type="button"
            className="bank-btn"
            disabled={busy || !configured}
            onClick={connect}
          >
            {busy ? "Connecting…" : "Connect with Plaid"}
          </button>
        </div>
        {msg && <p className="bank-msg">{msg}</p>}
        {err && <p className="error">{err}</p>}
      </div>
    </div>
  );
}
