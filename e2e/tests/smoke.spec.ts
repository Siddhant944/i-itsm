import { expect, test } from "@playwright/test";

test("placeholder UI shows the API as healthy", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "I-ITSM" })).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText("ok");
});
