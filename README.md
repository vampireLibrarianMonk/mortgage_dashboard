# 🏠 Mortgage Dashboard

A personal finance tool that helps you understand the true monthly cost of owning a home — not just the mortgage payment, but everything that comes with it: taxes, insurance, utilities, groceries, car expenses, college savings, and more. It shows you exactly how much money you'll have left over each month and helps you explore "what if" scenarios like making extra payments to pay off your loan faster.

---

## What Does This App Do?

Buying a home (or managing an existing mortgage) involves a lot more than just the loan payment. This dashboard brings all of your housing-related costs into one place so you can see the full picture:

- **Mortgage payment** — principal and interest based on your loan amount, term, and rate
- **Escrow costs** — property taxes, homeowner's insurance, PMI (if applicable), and HOA fees
- **Living expenses** — groceries, daycare, utilities, car costs, college savings, and anything else you spend money on each month
- **Extra payments** — see how paying extra toward your principal each month (or as lump sums) can save you years of payments and thousands in interest
- **Affordability check** — compares your total monthly obligations against your take-home pay and shows whether you're in the green or the red

You can save different scenarios (for example, different houses you're considering) and come back to them later. When you're ready, export a PDF report to share with your partner, financial advisor, or anyone else involved in the decision.

---

## Who Is This For?

- **First-time homebuyers** trying to figure out how much house they can afford
- **Current homeowners** who want to model the impact of extra principal payments
- **Anyone budgeting** who wants to see all their monthly expenses in one place relative to their mortgage

---

## Features at a Glance

| Feature | Description |
|---------|-------------|
| Two modes | Model a **new purchase** (enter home price, down payment, closing costs) or an **existing mortgage** (enter your outstanding balance) |
| Full budget | Enter all your expenses — household, utilities, vehicles, college savings, and custom line items |
| Extra payments | Add recurring extra principal (monthly, quarterly, semi-annual, or annual) or one-time lump sums |
| Payoff comparison | See your standard payoff date vs. accelerated payoff date, months saved, and interest saved |
| Amortization chart | Visual year-by-year chart showing principal vs. interest breakdown and remaining balance |
| Color-coded leftover | Green means you can afford it, red means you're over budget |
| Profile management | Save and load scenarios by street address |
| PDF export | Print a full detailed report with a custom filename (includes date and address) |
| Real-time calculation | Changes auto-calculate as you type (with a small delay so it doesn't overwhelm the server) |
| Flexible number input | Paste numbers with commas (like "350,000") and they work correctly |

---

## How It Works (The Simple Version)

```
┌─────────────────────┐          ┌─────────────────────┐
│    Your Browser     │          │     Python Server    │
│    (React App)      │◄────────►│     (FastAPI)        │
│                     │   JSON   │                      │
│  - Input forms      │          │  - All math happens  │
│  - Charts           │          │    here (single      │
│  - PDF export       │          │    source of truth)  │
└─────────────────────┘          └─────────────────────┘
```

1. You fill in the form on the left side of the screen (home price, income, expenses, etc.)
2. The browser sends your numbers to the Python server
3. The server does all the math (amortization schedules, totals, payoff dates)
4. The results appear on the right side of the screen in real-time

All calculations happen on the server so there's one source of truth — the frontend just displays the results.

---

## Getting Started

### What You'll Need

- **Python 3.12 or newer** — the backend language ([download here](https://www.python.org/downloads/))
- **Node.js 18 or newer** — needed to run the frontend build tools ([download here](https://nodejs.org/))
- **npm** — comes with Node.js, used to install frontend packages

### Step 1: Start the Backend (Python Server)

Open a terminal and navigate to the project folder:

```bash
cd mortgage_dashboard/backend
```

Create a virtual environment (keeps project packages separate from your system Python):

```bash
python -m venv ../.venv
```

Activate the virtual environment:

```bash
# On Linux or Mac:
source ../.venv/bin/activate

# On Windows (Command Prompt):
..\.venv\Scripts\activate

# On Windows (PowerShell):
..\.venv\Scripts\Activate.ps1
```

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Start the server:

```bash
uvicorn main:app --reload
```

You should see output indicating the server is running at **http://localhost:8000**. The `--reload` flag means it will automatically restart if you edit the code.

You can visit **http://localhost:8000/docs** in your browser to see the interactive API documentation (useful for developers but not required for normal use).

### Step 2: Start the Frontend (React App)

Open a **second terminal** (keep the backend running in the first one) and navigate to the frontend folder:

```bash
cd mortgage_dashboard/frontend
```

Install the required JavaScript packages:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

The app will be available at **http://localhost:5173**. Open that URL in your browser.

### Step 3: Use the App

Once both servers are running, you'll see the dashboard in your browser with:

- **Left panel** — all your input sections (home purchase details, loan terms, expenses, income, extra payments)
- **Right panel** — calculated results (monthly payment, payoff dates, affordability summary, amortization chart)

Just start filling in numbers and the results will update automatically.

---

## Always-On Local Hosting (Windows)

Want the app to come up automatically on every boot at a friendly URL like
**http://app.mortgage-dashboard/** (no port, no manually starting servers)?

The `deploy/` folder contains a registry-driven setup that:

- Serves the built frontend **and** API from FastAPI on a single high port (9001)
- Runs a **Caddy** reverse proxy on port 80 that routes `app.mortgage-dashboard` → the app
- Maps the hostname locally via the Windows hosts file
- Starts everything at boot (before login) via Task Scheduler

It's designed to host multiple local apps side by side — each gets its own
`app.<name>` hostname and its own port in the 9000s band. See **[`deploy/README.md`](deploy/README.md)**
for the full setup, adding new apps, and teardown steps.

---

## Using the App

### Choosing Your Mode

At the top of the inputs panel, you'll see a toggle between:

- **New Purchase** — use this if you're buying a new home. Enter the home price, down payment percentage (or dollar amount), closing costs, and earnest money.
- **Existing Mortgage** — use this if you already own your home. Enter your current outstanding balance and home value.

### Entering Expenses

Each section has fields for different expense categories:

- **Tax & Cost** — property tax (as a percentage of home value or a flat dollar amount), homeowner's insurance, PMI, HOA fees
- **Household** — daycare, groceries, general property upkeep
- **Utilities** — internet, phone, electric, gas, water
- **Vehicle** — car tax, gas, maintenance, insurance
- **College Savings** — annual contribution per child × number of children
- **Additional Expenses** — add as many custom line items as you need (monthly or annual)

### Adding Income

In the "Take Home Pay" section, add each income source. You can enter monthly or annual amounts — the app converts everything to monthly for comparison.

### Extra Principal Payments

This is where it gets interesting. You can model:

- **Recurring extra payments** — an additional amount paid on a schedule (monthly, quarterly, every 6 months, or annually). Set a start year, and optionally an end year (or leave it as "until payoff").
- **Lump sum payments** — one-time large payments in specific years (like a bonus or inheritance).

The results panel will show you how much time and interest these save you.

### Saving Profiles

Click "Save" to store your current scenario. Profiles are saved by street address so you can compare different properties. Load any saved profile to instantly restore all its values.

### Exporting a PDF

Once you have results, click the "📄 Export PDF" button in the header. This uses your browser's print dialog (choose "Save as PDF"). The filename is automatically set to include the date and address for easy filing.

---

## Running Tests

The backend has a test suite that verifies the math engine works correctly:

```bash
cd backend
source ../.venv/bin/activate
python -m pytest tests/ -v
```

This runs tests for:
- Down payment calculations (percentage and dollar modes)
- Loan amount calculations (with and without financed closing costs)
- Monthly payment accuracy
- Extra principal savings
- Affordability calculations
- Cash to close estimates

---

## Project Structure

```
mortgage_dashboard/
├── backend/                    # Python server (FastAPI)
│   ├── main.py                # API endpoints (calculate, profiles CRUD)
│   ├── models.py              # Data schemas — defines what inputs/outputs look like
│   ├── calculations.py        # The math engine — amortization, totals, payoff logic
│   ├── profiles_store.py      # Saves/loads profiles as JSON files
│   ├── requirements.txt       # Python package dependencies
│   └── tests/
│       └── test_calculations.py  # Automated tests for the math
│
├── frontend/                   # React app (TypeScript)
│   ├── src/
│   │   ├── App.tsx            # Main app layout (left panel + right panel)
│   │   ├── App.css            # Styling (including print styles for PDF)
│   │   ├── api.ts             # Talks to the Python server
│   │   ├── types.ts           # TypeScript type definitions
│   │   ├── hooks/
│   │   │   └── useCalculation.ts  # Auto-calculates when inputs change
│   │   └── components/
│   │       ├── ProfileManager.tsx     # Save/load profile UI
│   │       ├── inputs/               # Left panel form sections
│   │       │   ├── HousePurchase.tsx
│   │       │   ├── LoanTerms.tsx
│   │       │   ├── TaxAndCost.tsx
│   │       │   ├── HouseholdExpenses.tsx
│   │       │   ├── Utilities.tsx
│   │       │   ├── VehicleExpenses.tsx
│   │       │   ├── CollegeSavings.tsx
│   │       │   ├── AdditionalExpenses.tsx
│   │       │   ├── TakeHomePay.tsx
│   │       │   ├── ExtraPrincipal.tsx
│   │       │   ├── NumberInput.tsx
│   │       │   └── DualModeInput.tsx
│   │       └── results/              # Right panel displays
│   │           ├── ResultsPanel.tsx
│   │           ├── AmortizationChart.tsx
│   │           └── PrintReport.tsx
│   ├── package.json           # JavaScript package dependencies
│   └── index.html             # Entry point HTML file
│
├── .gitignore
└── README.md                  # This file
```

---

## Technology Stack (for the curious)

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | Python 3.12 + FastAPI | Fast, modern Python web framework with automatic API docs |
| Frontend | React 19 + TypeScript | Popular UI library with type safety to catch bugs early |
| Build tool | Vite | Extremely fast development server and build tool |
| Charts | Recharts | React-native charting library for the amortization graph |
| Data validation | Pydantic | Ensures the server receives valid data and gives clear errors if not |
| Testing | pytest | Simple, powerful Python test framework |

---

## API Endpoints

If you're a developer and want to interact with the backend directly:

| Method | Path | What it does |
|--------|------|--------------|
| `POST` | `/calculate` | Send all inputs, get back all calculated results + amortization schedule |
| `GET` | `/profiles` | List all saved profiles |
| `POST` | `/profiles` | Save a profile (by address) |
| `GET` | `/profiles/{id}` | Load a specific saved profile |
| `DELETE` | `/profiles/{id}` | Delete a saved profile |

Visit **http://localhost:8000/docs** when the backend is running to see the full interactive API documentation with example requests and responses.

---

## Troubleshooting

**The frontend shows "Calculating…" forever or shows an error**
- Make sure the backend is running on port 8000. The frontend expects to reach it at `http://localhost:8000`.

**"Module not found" errors when starting the backend**
- Make sure you activated the virtual environment (`source ../.venv/bin/activate`) before running `uvicorn`.

**npm install fails**
- Make sure you have Node.js 18+ installed. Check with `node --version`.

**Numbers look wrong or calculations seem off**
- Run the test suite (`python -m pytest tests/ -v`) to verify the math engine is working correctly. If tests pass, the issue is likely in the input values.

**PDF export doesn't work**
- The PDF export uses your browser's native print function. Make sure pop-ups aren't blocked. In the print dialog, select "Save as PDF" as the destination.

---

## License

This is a personal project. Feel free to fork and adapt it for your own mortgage planning needs.
