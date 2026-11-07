import { expect, test, type Page } from "@playwright/test";

// Every route renders its heading, without console errors or horizontal page overflow, at desktop and phone width.
const ROUTES: [string, RegExp][] = [
  ["/", /built from the prospectus/i],
  ["/dashboard", /Market overview/i],
  ["/ipos", /IPO discovery|IPOs/i],
  ["/calendar", /calendar/i],
  ["/analysis", /Financial analysis/i],
  ["/compare", /Compare/i],
  ["/history", /Listing history/i],
  ["/methodology", /Methodology/i],
  ["/data", /System health|Data/i],
];

function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    // the dev server's hot-reload socket is not an application error
    if (m.type() === "error" && !/webpack-hmr|_next\/webpack|HMR|WebSocket/i.test(m.text())) errors.push(m.text());
  });
  return errors;
}

async function noHorizontalOverflow(page: Page): Promise<void> {
  const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, "page wider than the viewport").toBeLessThanOrEqual(inner + 1);
}

for (const [path, heading] of ROUTES) {
  test(`${path} renders`, async ({ page }) => {
    const errors = trackErrors(page);
    const res = await page.goto(path);
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await noHorizontalOverflow(page);
    expect(errors).toEqual([]);
  });
}
