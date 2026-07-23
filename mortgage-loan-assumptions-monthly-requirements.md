# Mortgage & Loan Assumptions • Monthly

## Purpose

Define the functional requirements and screen layout for a mortgage planning workspace that helps a user:

- enter home purchase assumptions
- estimate required monthly housing cost
- model optional extra principal payments
- compare planned monthly housing outflow to take-home pay
- view cash-to-close, lifetime interest, payoff timing, and related budget impacts

This document describes the **business functionality**, not the current software implementation.

---

## Primary User Goal

The user wants one place to answer:

1. What is my required mortgage payment?
2. What is my full planned monthly housing outflow?
3. How much cash do I need to close?
4. How do extra principal payments affect payoff date, interest, and leftover cash?
5. Is the purchase affordable against take-home pay?

---

## Functional Scope

### 1. House Purchase Essentials

The user shall be able to enter:

- home price
- down payment as percent or dollars
- closing costs as percent or dollars
- earnest money as percent or dollars

The system shall calculate:

- down payment amount in dollars
- closing cost amount in dollars
- earnest money amount in dollars
- financed loan amount

### 2. Loan Terms

The user shall be able to enter:

- loan term in years
- annual interest rate
- mortgage start month
- mortgage start year

The system shall calculate:

- required monthly principal-and-interest payment
- first-month interest portion
- first-month principal portion
- payoff date under standard amortization

### 3. Annual Tax & Cost Inputs

The user shall be able to enter or enable:

- property tax as percent or annual dollars
- home insurance annual amount
- PMI monthly amount
- HOA monthly amount
- other home costs annual amount

The system shall normalize these into monthly amounts.

### 4. Household Expense Inputs

The user shall be able to include or exclude:

- daycare weekly
- groceries weekly
- utilities monthly
- property expenses monthly

### 5. Vehicle Expense Inputs

The user shall be able to include or exclude:

- car tax annual
- gasoline weekly
- car maintenance annual
- car insurance monthly

### 6. College Savings Inputs

The user shall be able to include or exclude:

- annual 529 contribution per child
- number of children

### 7. Additional Expense Log

The user shall be able to:

- add named recurring expenses
- enter each as monthly or annual
- edit rows
- delete rows

### 8. Take Home Pay Log

The user shall be able to:

- add named take-home income sources
- enter each as monthly or annual
- edit rows
- delete rows

### 9. Extra Principal Payments

The user shall be able to configure recurring extra principal:

- extra payment amount
- frequency: monthly, quarterly, semi-annual, annual
- start year
- end year

The user shall also be able to configure one-time lump sums:

- year
- amount

The system shall calculate:

- updated payoff date
- updated total interest
- updated total of mortgage payments
- months saved versus standard schedule
- interest savings versus standard schedule

### 10. Monthly Affordability Summary

The system shall calculate and display:

- required monthly housing total
- planned monthly housing total
- take-home pay
- monthly leftover

### 11. Cash to Close Summary

The system shall calculate:

- low and high prepaids/escrow estimate
- low and high estimated cash to close

### 12. Reporting / Export

The user shall be able to generate a written mortgage assumptions report suitable for PDF export.

---

## Business Rules

### Input Rules

- percent values shall not be negative
- percent values shall not exceed 100 where appropriate
- dollar inputs shall not be negative
- recurring extra principal years shall remain within the loan term
- lump-sum payments must be greater than zero to be added

### Calculation Rules

```text
down payment amount = home price * down payment %   OR entered dollars
closing costs amount = home price * closing costs % OR entered dollars
earnest money amount = home price * earnest %       OR entered dollars
loan amount = home price - down payment amount + financed closing costs
```

- required monthly mortgage payment shall mean required principal + interest only
- recurring extra principal shall not reduce the lender-required payment
- recurring extra principal shall increase planned monthly outflow
- monthly leftover shall use planned monthly housing total
- first-month interest shall represent only the first payment's interest share

### Communication Rules

The interface shall clearly distinguish between:

- required payment
- planned payment including extra principal
- first-month interest portion versus full payment
- raw percent input versus computed dollar output

---

## Required Summary Outputs

### Top-Level Monthly Summary

- planned monthly housing total
- take-home pay
- monthly leftover

### Purchase & Loan

- house price
- down payment dollar amount
- closing costs dollar amount
- optional note if closing costs came from a percent input
- earnest money credit
- total loan amount
- required mortgage monthly payment
- planned mortgage outflow monthly value when recurring extra principal is active
- first-month interest portion
- first-month principal portion

### Lifetime Mortgage Outcomes

- total of mortgage payments (P&I)
- total interest
- mortgage payoff date
- tax & cost monthly amount
- household monthly amount
- vehicle monthly amount
- college monthly amount
- additional expenses monthly amount

### Extra Principal Effects

When extra principal is configured, show:

- scheduled extra principal and frequency
- lump-sum extra principal total
- interest savings versus standard schedule
- months saved

### Cash to Close

- prepaids + escrow low
- estimated cash to close low
- prepaids + escrow high
- estimated cash to close high

---

## ASCII Layout

```text
+----------------------------------------------------------------------------------+
| Mortgage & Loan Assumptions • Monthly: $XX,XXX                                   |
+----------------------------------------------------------------------------------+
| LEFT: INPUTS                                      | RIGHT: RESULTS               |
|---------------------------------------------------+------------------------------|
| House Purchase Essentials                         | [Amortization Chart]         |
| - Home Price                                      |                              |
| - Down Payment [value] [ % | $ ]                  | Banner:                      |
| - Closing Costs [value] [ % | $ ]                 | Required Monthly Payment     |
| - Earnest Money [value] [ % | $ ]                 | Planned Monthly Outflow      |
|                                                   | Take Home Pay                |
| Loan Terms                                        | Leftover                     |
| - Loan Term                                       |                              |
| - Interest Rate                                   | Summary                      |
| - Start Month / Start Year                        |------------------------------|
|                                                   | Planned Monthly Housing Total|
| Annual Tax & Cost                                 | Take Home Pay                |
| - Property Tax [value] [ % | $/year ]             | Monthly Leftover             |
| - Home Insurance                                  |                              |
| - PMI                                             | Purchase & Loan              |
| - HOA                                             | - House Price                |
| - Other Home Costs                                | - Down Payment               |
|                                                   | - Closing Costs              |
| Household Expenses                                | - Earnest Money Credit       |
| - Daycare                                         | - Total Loan Amount          |
| - Groceries                                       | - Required Mortgage Monthly  |
| - Utilities                                       | - Planned Mortgage Outflow   |
| - Property Expenses                               | - First-Month Interest       |
|                                                   | - First-Month Principal      |
| Vehicle Expenses                                  |                              |
| - Car Tax                                         | Lifetime Mortgage Outcomes   |
| - Gasoline                                        | - Total Mortgage Payments    |
| - Car Maintenance                                 | - Total Interest             |
| - Car Insurance                                   | - Payoff Date                |
|                                                   | - Tax & Cost Monthly         |
| Kids College Savings                              | - Household Monthly          |
| - 529 Contribution                                | - Vehicle Monthly            |
| - Number of Kids                                  | - College Monthly            |
|                                                   | - Additional Expenses Monthly|
| Additional Expenses Log                           |                              |
| [add/edit/delete rows]                            | Extra Principal Effects      |
|                                                   | - Scheduled Extra Principal  |
| Take Home Pay Log                                 | - Lump Sum Extra Principal   |
| [add/edit/delete rows]                            | - Interest Savings           |
|                                                   | - Months Saved               |
| Extra Principal Payments                          |                              |
| - Scheduled Payment                               | Cash to Close                |
| - Frequency                                       | - Prepaids Low              |
| - Start Year                                      | - Cash to Close Low         |
| - End Year                                        | - Prepaids High             |
| - Lump Sum Rows                                   | - Cash to Close High        |
|                                                   |                              |
| [Calculate] [Save] [Generate PDF]                 |                              |
+----------------------------------------------------------------------------------+
```

---

## Terminology

- **Required Mortgage (Monthly)**: lender-required principal + interest payment
- **Planned Mortgage Outflow (Monthly)**: required mortgage plus monthly-equivalent recurring extra principal
- **First-Month Interest Portion**: interest share of the first required payment
- **First-Month Principal Portion**: principal share of the first required payment
- **Planned Monthly Housing Total**: all included monthly housing obligations plus recurring extra principal
- **Monthly Leftover**: take-home pay minus planned monthly housing total

---

## Open Questions

1. Should closing costs always be financed into the loan amount, or should the user choose financed vs cash?
2. Should monthly leftover include only housing-related categories, or all included budget categories as currently modeled?
3. Should the PDF mirror the screen grouping exactly?
