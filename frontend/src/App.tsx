import { useState } from "react";
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
import type { CalculateRequest, Classification } from "./types";
import "./App.css";

/** Props produced for a fixed-field line's inline M/D toggle. */
export interface MDProps {
  classification: Classification;
  onClassificationChange: (v: Classification) => void;
}
/** Factory that maps a canonical line key + default into MDToggle props. */
export type MakeMD = (key: string, defaultClass: Classification) => MDProps;

function App() {
  const { state, dispatch, result, loading, error } = useCalculation();
  const [profileAddress, setProfileAddress] = useState("");
  const [page, setPage] = useState<"dashboard" | "console" | "banks">("dashboard");

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
        </nav>
        {page === "dashboard" && result && (
          <button type="button" className="print-btn" onClick={handlePrint}>
            📄 Export PDF
          </button>
        )}
      </header>

      {page === "console" ? (
        <main className="console-page">
          <Console />
        </main>
      ) : page === "banks" ? (
        <main className="banks-page">
          <BankManager />
        </main>
      ) : (
        <>
      <ProfileManager currentState={state} onLoad={loadState} onAddressChange={setProfileAddress} />
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
          {result && <ResultsPanel result={result} purchaseMode={state.house_purchase.purchase_mode} discretionary={state.discretionary} />}
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
