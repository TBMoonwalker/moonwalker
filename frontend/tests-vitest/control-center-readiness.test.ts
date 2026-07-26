import { describe, expect, it } from 'vitest'

import { normalizeControlCenterBlockers } from '../src/control-center/blockers'
import { deriveControlCenterReadiness } from '../src/control-center/readiness'

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
}

describe('deriveControlCenterReadiness', () => {
  it('marks a complete safe dry-run configuration ready', () => {
    const readiness = deriveControlCenterReadiness(completeDryRunConfig)

    expect(readiness.complete).toBe(true)
    expect(readiness.dryRun).toBe(true)
    expect(readiness.nextMode).toBe('overview')
    expect(readiness.nextTarget).toBe('live-activation')
  })

  it('routes a recovery spacing blocker to advanced DCA controls', () => {
    const readiness = deriveControlCenterReadiness({
      ...completeDryRunConfig,
      dca: true,
      trade_mode: 'dynamic_dca',
      mstc: 4,
      sos: 2,
      dynamic_so_sizing_mode: 'recovery_target',
      ss: 0,
      dynamic_so_max_deal_quote: 300,
    })

    expect(readiness.complete).toBe(false)
    expect(readiness.blockers[0]).toMatchObject({
      key: 'ss',
      mode: 'advanced',
      target: 'dca',
    })
  })

  it('surfaces malformed backend blockers without trusting invalid rows', () => {
    const blockers = normalizeControlCenterBlockers([
      null,
      { key: '', message: 'ignored' },
      { key: 'signal_settings.api_key', message: 'Add the API key.' },
    ])

    expect(blockers).toHaveLength(1)
    expect(blockers[0]).toMatchObject({
      key: 'signal_settings.api_key',
      target: 'signal',
      description: 'Add the API key.',
    })
  })
})
