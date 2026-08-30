import { test, expect } from "@playwright/test";

const LONG_PERSON_NAME =
  "咕咕嘎嘎宇宙冷漠哈基米曼波椰果奶龙豪情在天自在极意豪一生有爱何惧风飞沙飞八分钱干飞马叮咚鸡叮咚鸡大狗大狗叫叫叫";

// Mock AstrBot bridge script injected before app loads
const MOCK_BRIDGE_INIT_SCRIPT = `
window.AstrBotPluginPage = {
  ready: async () => ({
    pluginName: "astrbot_plugin_identity_directory",
    displayName: "通讯录",
    pageName: "directory",
    isDark: false,
    locale: "zh-CN"
  }),
  getContext: () => ({ isDark: document.documentElement.classList.contains("dark") }),
  getLocale: () => "zh-CN",
  onContext: (cb) => { window.__onContextCb = cb; return () => {}; },
  apiGet: async (endpoint, params) => {
    if (endpoint === "stats") {
      return { persons: 4, accounts: 3, unlinked_accounts: 1, memberships: 2, aliases: 4 };
    }
    if (endpoint === "persons") {
      return {
        total: 4,
        items: [
          {
            person_id: "p1",
            canonical_name: "测试用户A",
            notes: "主要开发者",
            tags: ["管理员"],
            is_bot: false,
            is_archived: false,
            created_at: 1700000000,
            updated_at: 1700001000
          },
          {
            person_id: "p2",
            canonical_name: "测试用户B",
            notes: "程序员",
            tags: ["编辑"],
            is_bot: false,
            is_archived: false,
            created_at: 1700000000,
            updated_at: 1700002000
          },
          {
            person_id: "p3",
            canonical_name: "测试Bot",
            notes: "虚拟助理",
            tags: ["AI"],
            is_bot: true,
            is_archived: false,
            created_at: 1700000000,
            updated_at: 1700003000
          },
          {
            person_id: "p4",
            canonical_name: "${LONG_PERSON_NAME}",
            notes: "用于验证超长联系人名称不会撑破合并弹窗",
            tags: [],
            is_bot: false,
            is_archived: false,
            created_at: 1700000000,
            updated_at: 1700004000
          }
        ]
      };
    }
    if (endpoint === "persons/p1") {
      return {
        person_id: "p1",
        canonical_name: "测试用户A",
        notes: "主要开发者",
        tags: ["管理员"],
        is_bot: false,
        is_archived: false,
        created_at: 1700000000,
        updated_at: 1700001000,
        accounts: [
          {
            account_id: "a1",
            platform: "aiocqhttp",
            platform_instance_id: "萌依",
            platform_user_id: "100000001",
            username: "",
            person_id: "p1",
            first_seen: 1700000000,
            last_seen: 1700004000,
            alias_count: 2,
            memberships: [
              {
                membership_id: "m1",
                account_id: "a1",
                group_id: "100001",
                current_card: "群名片A",
                first_seen: 1700000000,
                last_seen: 1700004000
              }
            ]
          }
        ]
      };
    }
    if (endpoint === "accounts/a1/aliases") {
      return {
        items: [
          {
            alias_id: "al1",
            account_id: "a1",
            name: "群名片A",
            platform: "aiocqhttp",
            group_id: "100001",
            source: "observed",
            first_seen: 1700000000,
            last_seen: 1700004000
          }
        ]
      };
    }
    if (endpoint === "accounts") {
      return {
        items: [
          {
            account_id: "a1",
            platform: "aiocqhttp",
            platform_instance_id: "萌依",
            platform_user_id: "100000001",
            username: "",
            person_id: "p1",
            first_seen: 1700000000,
            last_seen: 1700004000,
            alias_count: 2,
            memberships: [
              {
                membership_id: "m1",
                account_id: "a1",
                group_id: "100001",
                current_card: "群名片A",
                first_seen: 1700000000,
                last_seen: 1700004000
              }
            ]
          }
        ]
      };
    }
    return { items: [] };
  },
  apiPost: async (endpoint, body) => {
    window.__lastApiPost = { endpoint, body };
    return { success: true };
  }
};
`;

test.describe("Identity Directory E2E", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(MOCK_BRIDGE_INIT_SCRIPT);
    await page.goto("/");
  });

  test("1. Renders title, stats badges, and contact list properly", async ({ page }) => {
    await expect(page.locator("h1")).toContainText("跨平台通讯录");
    // Verify Stats badges
    await expect(page.getByText("联系人:").first()).toBeVisible();
    await expect(page.getByText("未绑定账号:").first()).toBeVisible();

    // Verify Person Table rows
    await expect(page.getByRole("cell", { name: "测试用户A" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "测试用户B" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "测试Bot" })).toBeVisible();
  });

  test("2. Tab switching works with high-contrast active styling", async ({ page }) => {
    const personTab = page.getByRole("tab", { name: "联系人" });
    const accountTab = page.getByRole("tab", { name: "平台账号" });

    // Initially personTab is active
    await expect(personTab).toHaveAttribute("data-state", "active");
    await expect(accountTab).toHaveAttribute("data-state", "inactive");

    // Click Platform Accounts Tab
    await accountTab.click();
    await expect(accountTab).toHaveAttribute("data-state", "active");
    await expect(personTab).toHaveAttribute("data-state", "inactive");

    // Account table is now displayed
    await expect(page.getByRole("cell", { name: "100000001" })).toBeVisible();
  });

  test("3. Person detail opens as a SOLID right drawer (not transparent)", async ({ page }) => {
    // Click Edit on "测试用户A"
    const editBtn = page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "编辑" });
    await editBtn.click();

    // Drawer should appear
    const drawer = page.locator("aside[aria-label='联系人管理抽屉']");
    await expect(drawer).toBeVisible();

    // Verify SOLID opaque background
    const bg = await drawer.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");

    // Form fields are populated
    await expect(page.locator("#f-canonical")).toHaveValue("测试用户A");
    await expect(page.locator("#f-tags")).toHaveValue("管理员");
    await expect(page.locator("#f-notes")).toHaveValue("主要开发者");
    await expect(drawer.getByText("实例 萌依", { exact: true })).toBeVisible();

    // Close drawer via close button; the merge action belongs to the list entry only.
    await expect(drawer.getByRole("button", { name: /合并联系人/ })).toHaveCount(0);
    const closeBtn = drawer.getByRole("button").first();
    await closeBtn.click();
    await expect(drawer).not.toBeVisible();
  });

  test("4. Saving a person closes the drawer after the update succeeds", async ({ page }) => {
    await page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "编辑" })
      .click();

    const drawer = page.locator("aside[aria-label='联系人管理抽屉']");
    await expect(drawer).toBeVisible();
    await page.locator("#f-canonical").fill("修改后的用户");
    await drawer.getByRole("button", { name: "保存修改" }).click();

    await expect(drawer).not.toBeVisible();
    const postPayload = await page.evaluate(
      () =>
        (window as unknown as { __lastApiPost: { endpoint: string; body: unknown } }).__lastApiPost,
    );
    expect(postPayload).toEqual({
      endpoint: "persons/p1/update",
      body: {
        canonical_name: "修改后的用户",
        tags: ["管理员"],
        notes: "主要开发者",
        is_bot: false,
        is_archived: false,
      },
    });
  });

  test("5. Delete uses an in-page confirmation and closes after success", async ({ page }) => {
    await page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "编辑" })
      .click();

    const drawer = page.locator("aside[aria-label='联系人管理抽屉']");
    await drawer.getByRole("button", { name: "删除联系人" }).click();
    const alertDialog = page.getByRole("alertdialog");
    await expect(alertDialog).toBeVisible();
    await expect(alertDialog).toContainText("确定删除联系人？");

    await alertDialog.getByRole("button", { name: "取消" }).click();
    await expect(alertDialog).not.toBeVisible();
    await expect(drawer).toBeVisible();

    await drawer.getByRole("button", { name: "删除联系人" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "确认删除" }).click();
    await expect(drawer).not.toBeVisible();

    const postPayload = await page.evaluate(
      () =>
        (window as unknown as { __lastApiPost: { endpoint: string; body: unknown } }).__lastApiPost,
    );
    expect(postPayload).toEqual({ endpoint: "persons/p1/delete", body: {} });
  });

  test("4. Multi-select merge INTO current person from LIST TABLE with checkboxes", async ({
    page,
  }) => {
    // Click "合并" button directly in the row for "测试用户A"
    const mergeRowBtn = page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "合并" });
    await mergeRowBtn.click();

    // Merge dialog is visible with SOLID background
    const mergeDialog = page.getByRole("dialog");
    await expect(mergeDialog).toBeVisible();
    const bg = await mergeDialog.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");

    // Verify Header states target person is "测试用户A"
    await expect(mergeDialog.getByText("合并联系人进【测试用户A】")).toBeVisible();
    await expect(mergeDialog.getByText("当前合并主体（保留）：")).toBeVisible();

    // Candidates list shows other persons (测试用户B, 测试Bot)
    const userBItem = mergeDialog.getByText("测试用户B");
    const botItem = mergeDialog.getByText("测试Bot");
    await expect(userBItem).toBeVisible();
    await expect(botItem).toBeVisible();

    // Multi-select: Check "测试用户B" and "测试Bot"
    await userBItem.click();
    await botItem.click();

    // Verify Selected Counter & Warning
    await expect(mergeDialog.getByText("已勾选 2 个待合并联系人：")).toBeVisible();
    await expect(mergeDialog.getByText("不可逆合并：")).toBeVisible();

    // Action button states "确认将 2 人合并入【测试用户A】"
    const confirmBtn = mergeDialog.getByRole("button", {
      name: "确认将 2 人合并入【测试用户A】",
    });
    await expect(confirmBtn).toBeVisible();

    // Click confirm
    await confirmBtn.click();

    // Verify post payload contains target_person_id and source_person_ids
    const postPayload = await page.evaluate(
      () => (window as unknown as { __lastApiPost: { body: unknown } }).__lastApiPost.body,
    );
    expect(postPayload).toEqual({
      target_person_id: "p1",
      source_person_ids: ["p2", "p3"],
    });
  });

  test("7. Merge footer remains reachable with a long name in a narrow viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 936, height: 776 });
    await page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "合并" })
      .click();

    const dialog = page.getByRole("dialog");
    await dialog.getByText(LONG_PERSON_NAME, { exact: true }).click();

    const confirmBtn = dialog.getByRole("button", {
      name: "确认将 1 人合并入【测试用户A】",
    });
    await expect(confirmBtn).toBeVisible();

    const geometry = await dialog.evaluate((element, longName) => {
      const dialogRect = element.getBoundingClientRect();
      const footer = element.querySelector<HTMLElement>("[data-merge-footer]");
      const body = element.querySelector<HTMLElement>("[data-merge-scroll-body]");
      const selectedBadge = element.querySelector<HTMLElement>("[data-selected-source-badge]");
      const candidate = [...element.querySelectorAll<HTMLElement>("[data-merge-candidate]")].find(
        (node) => node.textContent?.includes(longName),
      );
      const action = element.querySelector<HTMLButtonElement>("[data-merge-confirm]");
      if (!footer || !body || !selectedBadge || !candidate || !action) {
        throw new Error(
          `merge layout missing: footer=${Boolean(footer)} body=${Boolean(body)} badge=${Boolean(selectedBadge)} candidate=${Boolean(candidate)} action=${Boolean(action)}`,
        );
      }
      const footerRect = footer.getBoundingClientRect();
      const bodyRect = body.getBoundingClientRect();
      const actionRect = action.getBoundingClientRect();
      return {
        dialogLeft: dialogRect.left,
        dialogRight: dialogRect.right,
        dialogClientWidth: element.clientWidth,
        dialogScrollWidth: element.scrollWidth,
        footerTop: footerRect.top,
        footerBottom: footerRect.bottom,
        bodyBottom: bodyRect.bottom,
        actionLeft: actionRect.left,
        actionRight: actionRect.right,
        actionBottom: actionRect.bottom,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        badgeClientWidth: selectedBadge.clientWidth,
        badgeScrollWidth: selectedBadge.scrollWidth,
        candidateClientHeight: candidate.clientHeight,
        candidateScrollHeight: candidate.scrollHeight,
      };
    }, LONG_PERSON_NAME);

    expect(geometry.dialogLeft).toBeGreaterThanOrEqual(0);
    expect(geometry.dialogRight).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(geometry.dialogScrollWidth).toBeLessThanOrEqual(geometry.dialogClientWidth + 1);
    expect(geometry.badgeScrollWidth).toBeLessThanOrEqual(geometry.badgeClientWidth + 1);
    expect(geometry.candidateScrollHeight).toBeLessThanOrEqual(geometry.candidateClientHeight + 1);
    expect(geometry.actionLeft).toBeGreaterThanOrEqual(geometry.dialogLeft);
    expect(geometry.actionRight).toBeLessThanOrEqual(geometry.dialogRight);
    expect(geometry.bodyBottom).toBeLessThanOrEqual(geometry.footerTop + 1);
    expect(geometry.footerBottom).toBeLessThanOrEqual(geometry.viewportHeight);
    expect(geometry.actionBottom).toBeLessThanOrEqual(geometry.viewportHeight);

    await confirmBtn.click();
    const postPayload = await page.evaluate(
      () => (window as unknown as { __lastApiPost: { body: unknown } }).__lastApiPost.body,
    );
    expect(postPayload).toEqual({
      target_person_id: "p1",
      source_person_ids: ["p4"],
    });
  });

  test("5. Create Person modal has SOLID background and form fields", async ({ page }) => {
    await page.getByRole("button", { name: "新建联系人" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const bg = await dialog.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");

    await expect(page.locator("#c-name")).toBeVisible();
  });

  test("6. Dark mode support check: Drawer & Dialog remain solid and readable", async ({
    page,
  }) => {
    // Enable dark mode class
    await page.evaluate(() => document.documentElement.classList.add("dark"));

    // Open Drawer
    await page
      .getByRole("row", { name: /测试用户A/ })
      .getByRole("button", { name: "编辑" })
      .click();
    const drawer = page.locator("aside[aria-label='联系人管理抽屉']");
    await expect(drawer).toBeVisible();

    const darkBg = await drawer.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(darkBg).not.toBe("rgba(0, 0, 0, 0)");
    expect(darkBg).not.toBe("transparent");
    // Dark mode background is dark (R < 60, G < 60, B < 60)
    const match = darkBg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
      const [_, r, g, b] = match.map(Number);
      expect(r).toBeLessThan(60);
      expect(g).toBeLessThan(60);
      expect(b).toBeLessThan(60);
    }
  });
});
