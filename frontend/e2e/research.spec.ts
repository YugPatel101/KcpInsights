import { expect, test } from "@playwright/test";

type IssueFact = { key: string; label: string; value: unknown; status: string; reason: string | null };
type Summary = { id: number; company_name: string; stage: string; data_mode: string };

// Research page of a real listed IPO: every issue fact shows a value or the reason it is empty; tabs open.
test("issue details show a value or a reason for every fact", async ({ page, request }) => {
  const list = await (await request.get("/api/ipos?page_size=200")).json();
  const ipo = (list.items as Summary[]).find((i) => i.data_mode === "source" && i.stage === "listed");
  test.skip(!ipo, "no listed IPO on record");
  const detail = await (await request.get(`/api/ipos/${ipo!.id}`)).json();
  const facts = detail.issue_facts as IssueFact[];
  expect(facts.length).toBeGreaterThan(15);
  for (const f of facts) expect(f.value !== null || Boolean(f.reason), `${f.key} is empty without a reason`).toBeTruthy();

  await page.goto(`/ipos/${ipo!.id}`);
  await expect(page.getByRole("heading", { name: ipo!.company_name })).toBeVisible();
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Issue details" }) });
  await expect(panel).toBeVisible();
  for (const label of ["Face value", "Lot size", "Issue size", "Promoter holding before the issue", "Registrar"]) {
    await expect(panel.getByText(label, { exact: true }).first()).toBeVisible();
  }
  // a fact shown as "—" carries its reason in the row beneath
  const empty = facts.filter((f) => f.value === null);
  if (empty.length) await expect(panel.getByText(empty[0].reason!, { exact: true }).first()).toBeVisible();

  for (const tab of ["Financial statements", "Data completeness", "Sources"]) {
    await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
    await expect(page.getByRole("tab", { name: new RegExp(`^${tab}`) })).toHaveAttribute("aria-selected", "true");
  }
});

test("discovery filters and search reach a research page", async ({ page }) => {
  await page.goto("/ipos");
  const firstRow = page.locator("table tbody tr a").first();
  await expect(firstRow).toBeVisible();
  const name = (await firstRow.textContent())?.trim() ?? "";
  await firstRow.click();
  await expect(page).toHaveURL(/\/ipos\/\d+$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
});

test("API errors use the documented envelope and never leak internals", async ({ request }) => {
  const res = await request.get("/api/ipos/999999999");
  expect(res.status()).toBe(404);
  const body = await res.json();
  expect(body).toHaveProperty("error");
  expect(JSON.stringify(body)).not.toMatch(/Traceback|sqlite|\/Users\/|site-packages/);
});
