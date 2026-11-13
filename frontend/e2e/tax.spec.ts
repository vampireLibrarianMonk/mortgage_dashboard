import { expect, test } from "@playwright/test";

// The ten 2025 tax documents ingested from
// Documents\Scans\Organized\Tax_Documents\2025 (see the 2025 fill-out session).
const DOC_NAMES = [
  "1095-C_Booz_Allen_Employer_Coverage_2025.pdf",
  "1099-INT_Navy_Federal_2025.pdf",
  "1099-NEC_Fay_Nutrition_Sara_2025.pdf",
  "1099-NEC_Fay_Nutrition_Sara_2025_Cover.pdf",
  "2025-Joint-WROS-TOD-0625-Consolidated-Form-1099.pdf",
  "W2_Patrick_Booz_Allen_2025_Copy_B.pdf",
  "W2_Sara_Inova_2025.pdf",
  "Form_3922_ESPP_Fidelity_2025.pdf",
  "2025_return.pdf",
  "2025_return_il.pdf",
];

test("tax prep 2025 shows all ten ingested documents", async ({ page }) => {
  await page.goto("/tax");
  await expect(page.getByRole("heading", { name: "Tax Picture 2025" })).toBeVisible();

  const rows = page.locator(".tax-doc-row:not(.tax-doc-head)");
  await expect(rows).toHaveCount(10);

  for (const name of DOC_NAMES) {
    await expect(page.locator(".tax-doc-name", { hasText: name })).toBeVisible();
  }
});

test("every 2025 document shows its detected form type and pipeline stage", async ({
  page,
}) => {
  await page.goto("/tax");
  const rows = page.locator(".tax-doc-row:not(.tax-doc-head)");
  await expect(rows).toHaveCount(10);

  // Nine documents reached 'extracted'; the NEC mailing cover stays 'classified'.
  await expect(
    page.locator(".tax-doc-row:not(.tax-doc-head) .tax-stage-extracted"),
  ).toHaveCount(9);
  await expect(
    page.locator(".tax-doc-row:not(.tax-doc-head) .tax-stage-classified"),
  ).toHaveCount(1);

  // The as-filed returns carry their own form types.
  await expect(
    page
      .locator(".tax-doc-row", { hasText: "2025_return.pdf" })
      .locator(".tax-form"),
  ).toHaveText("1040");
  await expect(
    page
      .locator(".tax-doc-row", { hasText: "2025_return_il.pdf" })
      .locator(".tax-form"),
  ).toHaveText("IL-1040");
  await expect(
    page
      .locator(".tax-doc-row", { hasText: "W2_Patrick_Booz_Allen_2025_Copy_B.pdf" })
      .locator(".tax-form"),
  ).toHaveText("W-2");
});

test("tax prep 2025 screenshot for the record", async ({ page }) => {
  await page.goto("/tax");
  await expect(page.locator(".tax-doc-row:not(.tax-doc-head)")).toHaveCount(10);
  await page.screenshot({
    path: "e2e/artifacts/tax-2025.png",
    fullPage: true,
  });
});

test("tax prep 2025 renders the as-filed summary layout", async ({ page }) => {
  await page.goto("/tax");
  await expect(page.locator(".tax-card-federal .tax-pic-label")).toHaveText(
    "Federal — as filed",
  );
  await expect(
    page
      .locator(".tax-card-federal .tax-kv", { hasText: "Adjusted gross income" }),
  ).toContainText("282,819.00");
  await expect(page.locator(".tax-card-federal .tax-kv-due")).toContainText(
    "8,934.00",
  );
  await expect(
    page.locator(".tax-card-state", { hasText: "Illinois" }).locator(".tax-pic-label"),
  ).toHaveText("Illinois — as filed");

  // Virginia's 760 is embedded in the federal e-file package -> as-filed card.
  await expect(
    page.locator(".tax-card-state", { hasText: "Virginia" }).locator(".tax-pic-label"),
  ).toHaveText("Virginia — as filed");
  await expect(page.locator(".tax-card-state", { hasText: "Virginia" })).toContainText(
    "14,349.00",
  );
  await expect(page.locator(".tax-card-state", { hasText: "Virginia" })).toContainText(
    "146.00",
  );

  // Salary rows per person + household strip.
  await expect(page.locator(".tax-kv-person", { hasText: "Patrick" })).toBeVisible();
  await expect(page.locator(".tax-kv-person", { hasText: "Sara" })).toBeVisible();
  await expect(
    page.locator(".tax-total-row", { hasText: "Household total" }),
  ).toContainText("279,469.79");

  // Year chips — five years (2027..2023), with the combined as-filed outcome
  // on the 2025 chip (federal owe + IL owe − VA refund).
  await expect(page.locator(".tax-chip")).toHaveCount(5);
  await expect(page.locator(".tax-chip", { hasText: "Owe 8,811.00" })).toBeVisible();
});

test("tax prep 2025 shows the HSA and 529 deductions with their jurisdictions", async ({
  page,
}) => {
  await page.goto("/tax");
  const section = page.locator(".tax-section", {
    hasText: "Deductions & adjustments",
  });
  await expect(section).toBeVisible();

  // HSA: claimed at zero on the federal return — contributions ran through
  // payroll (employer $4,495 each per Form 8889), $8,110 allowable unclaimed,
  // $240 of distributions taxable.
  const federal = section.locator(".tax-kv-block", {
    hasText: "Health savings account",
  });
  await expect(federal.locator(".tax-ded-badge")).toHaveText("Federal");
  await expect(federal).toContainText("0.00");
  await expect(federal).toContainText("$4,495");
  await expect(federal).toContainText("$8,110");

  // Virginia529: $4,000 off Virginia taxable income only — no federal benefit.
  const va = section.locator(".tax-kv-block", { hasText: "Virginia529" });
  await expect(va.locator(".tax-ded-badge")).toHaveText("Virginia");
  await expect(va).toContainText("4,000.00");
  await expect(va).toContainText("not deductible on the federal return");

  // Illinois: no 529 subtraction in the filed IL-1040 package.
  const il = section.locator(".tax-kv-block", { hasText: "Illinois 529" });
  await expect(il.locator(".tax-ded-badge")).toHaveText("Illinois");
  await expect(il).toContainText("none on file");
});

test("tax prep 2025 cross-checks the return against the documents", async ({
  page,
}) => {
  await page.goto("/tax");

  // Dependents from Schedule 8812 (count only).
  await expect(
    page.locator(".tax-section", { hasText: "Dependents (Schedule 8812)" }),
  ).toContainText("Qualifying children");

  // The cross-check: wages/interest tie, the dividend gap is surfaced, and
  // the capital row explains the statutory loss limit.
  const xc = page.locator(".tax-section", {
    hasText: "As-filed cross-check",
  });
  await expect(xc).toBeVisible();
  await expect(
    xc.locator(".tax-kv-block", { hasText: "Ordinary dividends" }),
  ).toContainText("3,863.41");
  await expect(
    xc.locator(".tax-kv-block", { hasText: "Ordinary dividends" }),
  ).toContainText("missing from the document set");
  await expect(
    xc.locator(".tax-kv-block", { hasText: "Capital gain/loss" }),
  ).toContainText("1,658");
});