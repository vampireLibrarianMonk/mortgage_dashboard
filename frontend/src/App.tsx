import { useEffect, useState } from "react";
import { useCalculation } from "./hooks/useCalculation";
import HousePurchaseSection from "./components/inputs/HousePurchase";
import LoanTermsSection from "./components/inputs/LoanTerms";
import TaxAndCostSection from "./components/inputs/TaxAndCost";
import HouseholdExpensesSection from "./components/inputs/HouseholdExpenses";
import UtilitiesSection from "./components/inputs/Utilities";
import VehicleExpensesSection from "./components/inputs/VehicleExpenses";
import ChildCareSection from "./components/inputs/ChildCare";
import PetCareSection from "./components/inputs/PetCare";
import Discretionary from "./components/inputs/Discretionary";
import AdditionalExpenses from "./components/inputs/AdditionalExpenses";
import TakeHomePay from "./components/inputs/TakeHomePay";
import ExtraPrincipalSection from "./components/inputs/ExtraPrincipal";
import Console from "./components/Console";
import BankManager from "./components/BankManager";
import ResultsPanel from "./components/results/ResultsPanel";
import PrintReport from "./components/results/PrintReport";
import ProfileManager from "./components/ProfileManager";
import TimelinePage from "./components/timeline/TimelinePage";
import ScenarioTabs from "./components/timeline/ScenarioTabs";
import TaxPrepPage from "./components/tax/TaxPrepPage";
import { saveProfile, systemRefresh } from "./api";
import type { CalculateRequest, Classification, TimelinePlan } from "./types";
import "./App.css";

/** Props produced for a fixed-field line's inline M/D toggle. */
export interface MDProps {
  classification: Classification;
  onClassificationChange: (v: Classification) => void;
}
/** Factory that maps a canonical line key + default into MDToggle props. */
export type MakeMD = (key: string, defaultClass: Classification) => MDProps;

type Page = "dashboard" | "console" | "banks" | "timeline" | "tax";

// Each tab is a real URL path so tabs can be opened/bookmarked independently
// (e.g. app.mortgage-dashboard/timeline). The backend serves index.html for any
// unknown path (SPA fallback), so deep links and refreshes work.
const PAGE_PATHS: Record<Page, string> = {
  dashboard: "/",
  console: "/console",
  banks: "/banks",
  timeline: "/timeline",
  tax: "/tax",
};

function pageFromPath(pathname: string): Page {
  const seg = pathname.replace(/^\/+/, "").split("/")[0].toLowerCase();
  if (seg === "console" || seg === "banks" || seg === "timeline" || seg === "tax") return seg;
  return "dashboard";
}

function App() {
  const { state, dispatch, result, loading, error } = useCalculation();
  const [profileAddress, setProfileAddress] = useState("");
  // Stable id of the currently loaded/saved profile (the property key). Null
  // until a profile is loaded or saved. Threaded into the results panel so the
  // move-in-repair ledger can scope to this property.
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [page, setPageState] = useState<Page>(() => pageFromPath(window.location.pathname));
  // Active tax year for the Tax Prep tab (defaults to 2025, the current corpus).
  const [taxYear, setTaxYear] = useState(2025);

  // Navigate to a tab by pushing its URL, so the address bar reflects the tab
  // and browser back/forward works.
  const setPage = (next: Page) => {
    setPageState(next);
    const path = PAGE_PATHS[next];
    if (window.location.pathname !== path) {
      window.history.pushState({ page: next }, "", path);
    }
  };

  // Keep the active tab in sync with back/forward navigation.
  useEffect(() => {
    const onPop = () => setPageState(pageFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const setField = (section: keyof CalculateRequest) => (field: string, value: unknown) => {
    dispatch({ type: "SET_FIELD", section, field, value });
  };

  const setSection = (section: keyof CalculateRequest) => (value: unknown) => {
    dispatch({ type: "SET_SECTION", section, value });
  };

  // Build inline M/D toggle props for a fixed-field line. Reads the current
  // override from state.classifications (falling back to the provided default)
  // and writes changes back into that map.
  const makeMD: MakeMD = (key, defaultClass) => ({
    classification: state.classifications[key] ?? defaultClass,
    onClassificationChange: (v: Classification) => {
      dispatch({
        type: "SET_SECTION",
        section: "classifications",
        value: { ...state.classifications, [key]: v },
      });
    },
  });

  const loadState = (data: CalculateRequest) => {
    dispatch({ type: "LOAD", data });
  };

  // Save the current profile (whole request, incl. timeline_plan) to the given
  // address. Used by the Timeline tab's Save button so the user can persist
  // without switching back to the Dashboard. Keeps profileAddress in sync so the
  // Dashboard's profile bar reflects the same address.
  const saveCurrentProfile = async (address: string) => {
    const trimmed = address.trim();
    if (!trimmed) return;
    const saved = await saveProfile(trimmed, state);
    setProfileAddress(trimmed);
    setActiveProfileId(saved.id);
  };

  // --- Timeline scenarios (named plans the user tabs between; per-profile) ---
  const scenarios = state.timeline_scenarios ?? [{ name: "Base", plan: state.timeline_plan }];
  const activeScenario = Math.min(state.active_scenario ?? 0, scenarios.length - 1);

  // Commit a new scenarios array + active index, mirroring the active plan into
  // timeline_plan (which the backend projection reads).
  const commitScenarios = (next: typeof scenarios, active: number) => {
    const idx = Math.max(0, Math.min(active, next.length - 1));
    dispatch({ type: "SET_SECTION", section: "timeline_scenarios", value: next });
    dispatch({ type: "SET_SECTION", section: "active_scenario", value: idx });
    dispatch({ type: "SET_SECTION", section: "timeline_plan", value: next[idx].plan });
  };

  // Edit the active scenario's plan (called by TimelinePage via onChange).
  const setActivePlan = (plan: TimelinePlan) => {
    const next = scenarios.map((s, i) => (i === activeScenario ? { ...s, plan } : s));
    commitScenarios(next, activeScenario);
  };

  const emptyPlan = (): TimelinePlan => ({
    settings: { starting_leftover: 0, carry_over_leftover: false, horizon_years: 10 },
    timelines: [],
    adjustments: [],
  });

  const selectScenario = (i: number) => commitScenarios(scenarios, i);
  const addScenario = () => {
    const next = [...scenarios, { name: `Scenario ${scenarios.length + 1}`, plan: emptyPlan() }];
    commitScenarios(next, next.length - 1);
  };
  const duplicateScenario = () => {
    const src = scenarios[activeScenario];
    const copy = { name: `${src.name} (copy)`, plan: structuredClone(src.plan) };
    const next = [...scenarios.slice(0, activeScenario + 1), copy, ...scenarios.slice(activeScenario + 1)];
    commitScenarios(next, activeScenario + 1);
  };
  const renameScenario = (i: number, name: string) => {
    const next = scenarios.map((s, idx) => (idx === i ? { ...s, name } : s));
    commitScenarios(next, activeScenario);
  };
  const deleteScenario = (i: number) => {
    if (scenarios.length <= 1) return;
    const next = scenarios.filter((_, idx) => idx !== i);
    const active = i <= activeScenario ? Math.max(0, activeScenario - 1) : activeScenario;
    commitScenarios(next, active);
  };

  // Manual "Refresh services" — runs the deploy health check on demand (relaunch
  // the proxy / sibling app if down). Replaces the old every-5-min pop-up task.
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const handleRefreshServices = async () => {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const res = await systemRefresh();
      setRefreshMsg(res.ok ? "✔ services healthy" : "⚠ see details");
      // Surface the check's output in the console for the curious.
      console.info("service refresh:\n" + res.output.join("\n"));
    } catch {
      setRefreshMsg("refresh failed");
    } finally {
      setRefreshing(false);
      setTimeout(() => setRefreshMsg(null), 4000);
    }
  };

  const handlePrint = () => {
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 16).replace(/[-:T]/g, (m) => m === "T" ? "_" : m === ":" ? "" : m);
    const addr = profileAddress.trim().replace(/[^a-zA-Z0-9]/g, "_").replace(/_+/g, "_") || "no_address";
    const filename = `${dateStr}_${addr}_budget_board`;
    const originalTitle = document.title;
    document.title = filename;
    window.print();
    setTimeout(() => { document.title = originalTitle; }, 1000);
  };

  return (
    <div className="app">
      <header>
        <h1>Mortgage &amp; Loan Assumptions</h1>
        <nav className="page-nav">
          <button
            type="button"
            className={page === "dashboard" ? "page-tab active" : "page-tab"}
            onClick={() => setPage("dashboard")}
          >
            Dashboard
          </button>
          <button
            type="button"
            className={page === "console" ? "page-tab active" : "page-tab"}
            onClick={() => setPage("console")}
          >
            Console
          </button>
          <button
            type="button"
            className={page === "banks" ? "page-tab active" : "page-tab"}
            onClick={() => setPage("banks")}
          >
            Banks
          </button>
          <button
            type="button"
            className={page === "timeline" ? "page-tab active" : "page-tab"}
            onClick={() => setPage("timeline")}
          >
            Timeline
          </button>
          <button
            type="button"
            className={page === "tax" ? "page-tab active" : "page-tab"}
            onClick={() => setPage("tax")}
          >
            Tax Prep
          </button>
        </nav>
        <div className="header-actions">
          <button
            type="button"
            className="refresh-svc-btn"
            onClick={handleRefreshServices}
            disabled={refreshing}
            title="Re-check services and restart the proxy / other app if they're down"
          >
            {refreshing ? "⟳ Refreshing…" : "⟳ Refresh services"}
          </button>
          {refreshMsg && <span className="refresh-svc-msg">{refreshMsg}</span>}
          {page === "dashboard" && result && (
            <button type="button" className="print-btn" onClick={handlePrint}>
              📄 Export PDF
            </button>
          )}
        </div>
      </header>

      {page === "console" ? (
        <main className="console-page">
          <Console />
        </main>
      ) : page === "banks" ? (
        <main className="banks-page">
          <BankManager />
        </main>
      ) : page === "timeline" ? (
        <main className="timeline-page">
          <ScenarioTabs
            scenarios={scenarios}
            active={activeScenario}
            onSelect={selectScenario}
            onAdd={addScenario}
            onDuplicate={duplicateScenario}
            onRename={renameScenario}
            onDelete={deleteScenario}
          />
          <TimelinePage
            plan={scenarios[activeScenario].plan}
            onChange={setActivePlan}
            result={result}
            address={profileAddress}
            onSave={saveCurrentProfile}
          />
        </main>
      ) : page === "tax" ? (
        <main className="tax-page">
          <TaxPrepPage year={taxYear} onYearChange={setTaxYear} />
        </main>
      ) : (
        <>
      <ProfileManager currentState={state} onLoad={loadState} onAddressChange={setProfileAddress} onActiveIdChange={setActiveProfileId} />
      <main className="layout">
        <div className="inputs-panel">
          <HousePurchaseSection data={state.house_purchase} onChange={setField("house_purchase")} />
          <LoanTermsSection data={state.loan_terms} onChange={setField("loan_terms")} />
          <TaxAndCostSection data={state.tax_and_cost} onChange={setField("tax_and_cost")} makeMD={makeMD} />
          <HouseholdExpensesSection data={state.household_expenses} onChange={setField("household_expenses")} makeMD={makeMD} />
          <UtilitiesSection data={state.utilities} onChange={setField("utilities")} makeMD={makeMD} />
          <VehicleExpensesSection data={state.vehicle_expenses} onChange={setField("vehicle_expenses")} makeMD={makeMD} />
          <ChildCareSection data={state.child_care} onChange={setField("child_care")} makeMD={makeMD} />
          <PetCareSection data={state.pet_care} onChange={setField("pet_care")} makeMD={makeMD} />
          <Discretionary data={state.discretionary} onChange={setSection("discretionary")} />
          <AdditionalExpenses data={state.additional_expenses} onChange={setSection("additional_expenses")} />
          <TakeHomePay data={state.take_home_pay} onChange={setSection("take_home_pay")} />
          <ExtraPrincipalSection data={state.extra_principal} onChange={setSection("extra_principal")} />
        </div>
        <div className="results-column">
          {loading && <p className="loading">Calculating…</p>}
          {error && <p className="error">{error}</p>}
          {result && <ResultsPanel result={result} purchaseMode={state.house_purchase.purchase_mode} discretionary={state.discretionary} profileId={activeProfileId} />}
        </div>
      </main>

      {/* Hidden print-only report */}
      {result && (
        <div className="print-only">
          <PrintReport result={result} state={state} />
        </div>
      )}
        </>
      )}
    </div>
  );
}

export default App;
