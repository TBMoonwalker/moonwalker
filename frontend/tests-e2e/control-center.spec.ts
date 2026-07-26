import { expect, test } from '@playwright/test'

const completeDryRunConfig = {
  timezone: 'Europe/Vienna',
  signal: 'csv_signal',
  signal_settings: JSON.stringify({ csv_source: 'signals.csv' }),
  exchange: 'binance',
  timeframe: '1h',
  key: 'test-key',
  secret: 'test-secret',
  currency: 'USDC',
  max_bots: 2,
  bo: 10,
  tp: 1,
  capital_max_fund: 100,
  history_lookback_time: '180d',
  dca: false,
  dry_run: true,
  config_updated_at: '2026-07-25T12:00:00Z',
}

test.beforeEach(async ({ page }) => {
  await page.route('**/config/all', async (route) => {
    await route.fulfill({ json: completeDryRunConfig })
  })
  await page.route('**/config/freshness', async (route) => {
    await route.fulfill({
      json: { updated_at: completeDryRunConfig.config_updated_at },
    })
  })
})

test('renders the safe dry-run control center mission', async ({ page }) => {
  await page.goto('/control-center')

  await expect(
    page.getByRole('heading', { name: 'Safe dry-run setup is ready' }),
  ).toBeVisible()
  await expect(
    page.getByText('Moonwalker is configured for safe dry-run operation.'),
  ).toBeVisible()
})

test('keeps the mission heading inside a 375px viewport', async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, 'mobile-only layout assertion')
  await page.goto('/control-center')

  const heading = page.getByRole('heading', {
    name: 'Safe dry-run setup is ready',
  })
  await expect(heading).toBeVisible()
  const box = await heading.boundingBox()

  expect(box).not.toBeNull()
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(375)
})
