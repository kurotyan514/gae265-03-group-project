import { expect, type Page, test } from "@playwright/test";
import { ADMIN_EMAIL, skipUnlessAdmin } from "./helpers";

// 後台的不收錄區（/admin/excluded）：看被設成不收錄的條文，單條或整個險種收錄回來，永久刪除快照。
// 登入用後端的測試登入（沒開 DEV_LOGIN_ENABLED 時略過）；API 全部攔截成固定回應，不改開發資料庫。

const ITEMS = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    insurance_code: "CHUBB10",
    insurance_name: "海外急難援助服務內容",
    article_no: 9,
    chapter: "條文九",
    title: "急難援助服務內容",
    content: "第一項：旅行諮詢與醫療轉介。",
    section: null,
    subsection: null,
    reason: "不是條款",
    excluded_at: "2026-11-09T03:00:00Z",
    whole_insurance: true,
    in_catalog: false,
    insurance_exists: false,
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    insurance_code: "CHUBB10",
    insurance_name: "海外急難援助服務內容",
    article_no: 10,
    chapter: "條文十",
    title: "服務時間",
    content: "全年無休。",
    section: null,
    subsection: null,
    reason: "不是條款",
    excluded_at: "2026-11-09T03:00:00Z",
    whole_insurance: true,
    in_catalog: true, // 重新上傳又讀進來了
    insurance_exists: false,
  },
];

async function loginToExcluded(
  page: Page,
  request: Parameters<Parameters<typeof test>[2]>[0]["request"],
) {
  const config = await (await request.get("/api/v1/auth/config")).json();
  test.skip(!config.dev_login, "後端沒有設 DEV_LOGIN_ENABLED=true");
  await page.goto("/login?next=%2Fadmin%2Fexcluded");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByRole("button", { name: "測試登入" }).click();
  await expect(page).toHaveURL(/\/admin\/excluded$/);
  await skipUnlessAdmin(page);
}

function mockList(page: Page) {
  return page.route("**/api/v1/admin/excluded?**", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { total: ITEMS.length, items: ITEMS } })
      : route.fallback(),
  );
}

test("未登入進入不收錄區會被帶到登入頁", async ({ page }) => {
  await page.goto("/admin/excluded");
  await expect(page).toHaveURL(/\/login\?.*next=%2Fadmin%2Fexcluded/);
});

test("清單帶出標示：條文表已有同一條、險種已不在", async ({ page, request }) => {
  await mockList(page);
  await loginToExcluded(page, request);

  await expect(page.getByTestId("excluded-total")).toContainText("共 2 筆");
  await expect(page.getByTestId("excluded-CHUBB10-9")).toContainText("整個險種");
  await expect(page.getByTestId("excluded-CHUBB10-9")).toContainText("險種已不在，收錄時一併建立");
  await expect(page.getByTestId("excluded-CHUBB10-10")).toContainText("條文表已有同一條");
});

test("單條收錄回來：展開看內文、送出 ids、顯示結果與略過的原因", async ({ page, request }) => {
  await mockList(page);
  const sent: unknown[] = [];
  await page.route("**/api/v1/admin/excluded/restore", async (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        restored: [{ insurance_code: "CHUBB10", article_no: 9 }],
        skipped: [
          {
            id: ITEMS[1]?.id,
            insurance_code: "CHUBB10",
            article_no: 10,
            reason: "條文表裡已經有這一條",
          },
        ],
        insurances_created: ["CHUBB10"],
        message: "已收錄回來 1 條；重新建立險種 CHUBB10；略過 1 條",
      },
    });
  });
  await loginToExcluded(page, request);

  await page.getByTestId("excluded-CHUBB10-9").click();
  await expect(page.locator("pre").first()).toContainText("旅行諮詢與醫療轉介");
  await page.getByTestId("restore-rule").click();

  await expect(page.getByTestId("excluded-notice")).toContainText("已收錄回來 1 條");
  await expect(page.getByTestId("excluded-notice")).toContainText("條文表裡已經有這一條");
  expect(sent).toEqual([{ ids: [ITEMS[0]?.id] }]);
});

test("整個險種收錄回來：篩選險種後才出現，一次送出全部 ids", async ({ page, request }) => {
  await mockList(page);
  const sent: unknown[] = [];
  await page.route("**/api/v1/admin/excluded/restore", async (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({
      json: { restored: [], skipped: [], insurances_created: [], message: "已收錄回來 0 條" },
    });
  });
  await loginToExcluded(page, request);
  await expect(page.getByTestId("restore-insurance")).toHaveCount(0); // 還沒指定險種

  await page.getByTestId("excluded-code").fill("CHUBB10");
  await page.getByRole("button", { name: "篩選" }).click();
  await expect(page.getByTestId("restore-insurance")).toContainText("整個險種收錄回來（2 條）");
  await page.getByTestId("restore-insurance").click();

  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ ids: [ITEMS[0]?.id, ITEMS[1]?.id] });
});

test("永久刪除快照：先確認後果再送出 DELETE", async ({ page, request }) => {
  await mockList(page);
  const sent: string[] = [];
  await page.route("**/api/v1/admin/excluded/*", async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    sent.push(route.request().url());
    return route.fulfill({ json: { message: "已從不收錄區刪除，之後收錄不回來了" } });
  });
  await loginToExcluded(page, request);

  await page.getByTestId("excluded-CHUBB10-9").click();
  await page.getByTestId("delete-excluded").click();
  expect(sent).toHaveLength(0); // 還沒確認
  await expect(page.getByText("刪除後就收錄不回來了")).toBeVisible();
  await page.getByTestId("delete-excluded-yes").click();

  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toMatch(new RegExp(`/admin/excluded/${ITEMS[0]?.id}$`));
  await expect(page.getByTestId("excluded-notice")).toContainText("收錄不回來了");
});

test("收錄失敗（向量服務無法使用）時顯示原因", async ({ page, request }) => {
  await mockList(page);
  await page.route("**/api/v1/admin/excluded/restore", (route) =>
    route.fulfill({
      status: 502,
      json: { detail: "向量服務無法使用，沒有任何條文被收錄回來" },
    }),
  );
  await loginToExcluded(page, request);

  await page.getByTestId("excluded-CHUBB10-9").click();
  await page.getByTestId("restore-rule").click();

  await expect(page.getByTestId("excluded-notice")).toContainText("沒有任何條文被收錄回來");
});
