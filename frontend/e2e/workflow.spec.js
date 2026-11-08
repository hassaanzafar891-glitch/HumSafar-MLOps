import { test, expect } from "@playwright/test";
test("two real browser sessions complete the application workflow", async ({
  browser,
}) => {
  const first = await browser.newContext(),
    second = await browser.newContext();
  const owner = await first.newPage(),
    member = await second.newPage();
  const suffix = Date.now();
  async function registerAndLogin(page, email, name) {
    await page.goto("/register");
    await page.getByLabel("Your name", { exact: true }).fill(name);
    await page.getByLabel("Email address").fill(email);
    await page
      .getByLabel("Password", { exact: true })
      .fill("Browser-fixture-password!");
    await page
      .getByRole("button", { name: "Create account", exact: true })
      .click();
    await expect(
      page.getByText("Account created. Log in to start planning."),
    ).toBeVisible();
    await page.getByLabel("Email address").fill(email);
    await page
      .getByLabel("Password", { exact: true })
      .fill("Browser-fixture-password!");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/dashboard/);
  }
  await registerAndLogin(
    owner,
    `owner-${suffix}@example.com`,
    "Browser organizer",
  );
  await owner
    .getByLabel("Group name", { exact: true })
    .fill("Browser-tested adventure");
  await owner
    .getByRole("button", { name: "Create group", exact: true })
    .click();
  await expect(
    owner.getByRole("heading", { name: "Browser-tested adventure" }),
  ).toBeVisible();
  await owner.getByRole("button", { name: "Show code" }).click();
  const code = await owner
    .getByLabel("Private invitation code", { exact: true })
    .inputValue();
  await registerAndLogin(
    member,
    `member-${suffix}@example.com`,
    "Browser companion",
  );
  await member
    .getByLabel("Private invitation code", { exact: true })
    .fill(code);
  await member.getByRole("button", { name: "Join group", exact: true }).click();
  await expect(
    member.getByRole("heading", { name: "Browser-tested adventure" }),
  ).toBeVisible();
  for (const page of [owner, member]) {
    await page
      .getByLabel("Interests and categories (comma-separated)")
      .fill("mountains, hiking, lakes, nature");
    await page
      .getByLabel("Preferred countries (optional)")
      .selectOption(page === owner ? "Pakistan" : "United States");
    await page.getByLabel("Minimum budget").fill("100");
    await page.getByLabel("Maximum budget").fill("500");
    await page.getByLabel("Currency (3 uppercase letters)").fill("USD");
    await page
      .getByLabel("Travel start date")
      .fill(page === owner ? "2030-06-01" : "2030-06-03");
    await page
      .getByLabel("Travel end date")
      .fill(page === owner ? "2030-06-10" : "2030-06-08");
    await page
      .getByRole("button", { name: "Save preferences", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "Preferences saved." }),
    ).toBeVisible();
  }
  await owner
    .getByRole("button", { name: "Refresh group", exact: true })
    .click();
  await expect(
    owner.getByText("2030-06-03 — 2030-06-08", { exact: true }),
  ).toBeVisible();
  await expect(
    owner.getByText(/Members prefer different countries/),
  ).toBeVisible();
  await owner
    .getByRole("button", { name: "Recommendations", exact: true })
    .click();
  await owner
    .getByRole("button", { name: "Generate recommendations", exact: true })
    .click();
  await expect(
    owner.getByText("Recommendations generated.", { exact: true }),
  ).toBeVisible();
  await expect(
    owner.getByText(/New accounts use stated preferences/),
  ).toBeVisible();
  await expect(
    owner.getByText(/No budget filtering was applied/),
  ).not.toBeVisible();
  await owner.getByText("How recommendations work", { exact: true }).click();
  await expect(
    owner.getByText(/No budget filtering was applied/),
  ).toBeVisible();
  await owner.getByText("How recommendations work", { exact: true }).click();
  const card = owner.locator(".destination-card").first();
  const name = await card.getByRole("heading").innerText();
  await card.getByRole("button", { name: "Vote for this place" }).click();
  await expect(card.getByText("1 group votes", { exact: true })).toBeVisible();
  await member
    .getByRole("button", { name: "Refresh group", exact: true })
    .click();
  await member
    .getByRole("button", { name: "Recommendations", exact: true })
    .click();
  const memberCard = member
    .locator(".destination-card")
    .filter({ has: member.getByRole("heading", { name, exact: true }) });
  await memberCard.getByRole("button", { name: "Vote for this place" }).click();
  await expect(
    memberCard.getByText("2 group votes", { exact: true }),
  ).toBeVisible();
  await expect(
    member.getByText("Add to itinerary", { exact: true }),
  ).toHaveCount(0);
  await owner.getByRole("button", { name: "Itinerary", exact: true }).click();
  await expect(
    owner.getByText("A shared adventure, still unwritten", { exact: true }),
  ).toBeVisible();
  await owner
    .getByRole("button", { name: "Recommendations", exact: true })
    .click();
  await card.getByText("Add to itinerary", { exact: true }).click();
  await card.getByLabel(`Position for ${name}`).fill("1");
  await expect(card.getByLabel(`Visit date for ${name}`)).toHaveAttribute(
    "min",
    "2030-06-03",
  );
  await expect(card.getByLabel(`Visit date for ${name}`)).toHaveAttribute(
    "max",
    "2030-06-08",
  );
  await card.getByLabel(`Visit date for ${name}`).fill("2030-06-05");
  await card
    .getByLabel(`Notes for ${name}`)
    .fill("Isolated browser workflow fixture; not a booking");
  await card
    .getByRole("button", { name: "Add itinerary item", exact: true })
    .click();
  await expect(
    owner.getByText("Added to itinerary.", { exact: true }),
  ).toBeVisible();
  await owner.getByRole("button", { name: "Itinerary", exact: true }).click();
  await expect(owner.getByRole("heading", { name, exact: true })).toBeVisible();
  // Each member changes only their own availability/restrictions.
  await member
    .getByRole("button", { name: "Preferences", exact: true })
    .click();
  await member.getByLabel("Travel start date").fill("2030-07-01");
  await member.getByLabel("Travel end date").fill("2030-07-10");
  await member.getByLabel("Country flexibility").selectOption("mandatory");
  await member
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    member.getByText("No shared dates yet", { exact: true }),
  ).toBeVisible();
  await owner
    .getByRole("button", { name: "Refresh group", exact: true })
    .click();
  await owner.getByRole("button", { name: "Preferences", exact: true }).click();
  await owner.getByLabel("Country flexibility").selectOption("mandatory");
  await owner
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    owner.getByText("Country restrictions need attention"),
  ).toBeVisible();
  await expect(
    owner.getByRole("button", { name: /Consider Pakistan/ }),
  ).toHaveCount(0);
  // Explicitly make just the owner's country wish flexible; member stays mandatory US.
  await owner.getByLabel("Country flexibility").selectOption("preferred");
  await owner
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await owner.getByRole("button", { name: /Consider United States/ }).click();
  await expect(
    owner.getByLabel("Country filter (optional, exact catalog label)"),
  ).toHaveValue("United States");
  await owner
    .getByRole("button", { name: "Generate recommendations", exact: true })
    .click();
  await expect(
    owner.getByText("Recommendations generated.", { exact: true }),
  ).toBeVisible();
  const alternativeCard = owner.locator(".destination-card").first();
  const refugePhoto = owner
    .locator(".destination-card")
    .filter({
      has: owner.getByRole("heading", {
        name: "Hanalei National Wildlife Refuge",
        exact: true,
      }),
    })
    .locator(".photo-card img");
  await refugePhoto.scrollIntoViewIfNeeded();
  await expect
    .poll(() =>
      refugePhoto.evaluate((img) => img.complete && img.naturalWidth > 0),
    )
    .toBe(true);
  const alternativeName = await alternativeCard
    .getByRole("heading")
    .innerText();
  await alternativeCard.getByText("Add to itinerary", { exact: true }).click();
  await expect(
    alternativeCard.getByLabel(`Visit date for ${alternativeName}`),
  ).toBeDisabled();
  await owner.screenshot({
    path: "test-results/group-planning-desktop.png",
    fullPage: true,
  });
  expect(
    await owner.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0);
  await owner.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(owner).toHaveURL(/login/);
  await first.close();
  await second.close();
});
test("landing and catalog work on mobile without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /A world to explore/ }),
  ).toBeVisible();
  await expect(page.locator(".destination-card").first()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/landing-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Explore", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Somewhere worth sharing." }),
  ).toBeVisible();
  await page.getByLabel("Country or territory").selectOption("Pakistan");
  await expect(
    page.getByText("69 matching attraction listings", { exact: false }),
  ).toBeVisible();
  await page.getByLabel("Search catalog").fill("Ansoo");
  await expect(
    page.getByRole("heading", { name: "Ansoo Lake", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "View details ↗" }).click();
  await expect(page.locator("dialog")).toBeVisible();
  const photo = page.locator("dialog img");
  await expect(photo).toHaveAttribute(
    "alt",
    "Ansoo Lake, Kaghan Valley, Pakistan",
  );
  await expect
    .poll(() => photo.evaluate((img) => img.complete && img.naturalWidth > 0))
    .toBe(true);
  await expect(
    page.locator("dialog").getByRole("link", { name: "CC BY-SA 4.0" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/destination-photo-mobile.png",
    fullPage: false,
  });
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog")).not.toBeVisible();
});

test("verified Hawaii photographs load with credits and consistent card proportions", async ({
  page,
}) => {
  await page.goto("/explore");
  await page.getByLabel("Country or territory").selectOption("United States");
  await page.getByLabel("Search catalog").fill("Dole Plantation");
  const card = page.locator(".destination-card").filter({
    has: page.getByRole("heading", { name: "Dole Plantation", exact: true }),
  });
  const photograph = card.locator(".photo-card img");
  await expect
    .poll(() =>
      photograph.evaluate((img) => img.complete && img.naturalWidth > 0),
    )
    .toBe(true);
  await expect(photograph).toHaveAttribute("src", /dole-plantation-960.webp/);
  const dimensions = await photograph.boundingBox();
  expect(dimensions.width / dimensions.height).toBeCloseTo(1.6, 1);
  await card.getByRole("button", { name: "View details ↗" }).click();
  await expect(
    page.locator("dialog").getByRole("link", { name: "CC BY-SA 2.0" }),
  ).toBeVisible();
  await expect(
    page
      .locator("dialog")
      .getByRole("link", { name: /Kristina D.C. Hoeppner/ }),
  ).toHaveAttribute(
    "href",
    "https://commons.wikimedia.org/wiki/File:Dole_Plantation.jpg",
  );
  await page.screenshot({
    path: "test-results/verified-hawaii-photo-desktop.png",
    fullPage: false,
  });
});
