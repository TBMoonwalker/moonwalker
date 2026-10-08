import { describe, expect, it } from 'vitest'

import {
  buildSignalSettingsValue,
  buildVolumeConfig,
  getDefaultHistoryLookbackByTimeframe,
  isWebsocketUrl,
  normalizePairEntries,
  parseStructuredConfigValue,
  parseSymbolListToArray,
  parseVolumeLimitToNumber,
  serializeConfigValue,
  splitEntries,
  toNullableConfigString,
  toTokenOnlyEntries,
} from '../src/helpers/configForm'

describe('config form contracts', () => {
  it('preserves explicit typed update payloads', () => {
    expect(serializeConfigValue(false, 'bool')).toEqual({
      value: false,
      type: 'bool',
    })
  })

  it('round-trips normalized volume limits', () => {
    const encoded = buildVolumeConfig(2_500_000)

    expect(encoded).toEqual({ size: 2.5, range: 'M' })
    expect(parseVolumeLimitToNumber(encoded)).toBe(2_500_000)
    expect(parseVolumeLimitToNumber({ size: 'NaN', range: 'M' })).toBeNull()
  })

  it('normalizes pair and history inputs deterministically', () => {
    expect(parseSymbolListToArray('btc/usdc, ETH-USDC\nSOL/USDC')).toEqual([
      'btc/usdc',
      'ETH-USDC',
      'SOL/USDC',
    ])
    expect(normalizePairEntries('btc, eth/usdt', 'USDC')).toBe(
      'BTC/USDC,ETH/USDT',
    )
    expect(getDefaultHistoryLookbackByTimeframe('4h')).toBe('1y')
  })

  it.each([
    ['1m', '30d'],
    ['15m', '90d'],
    ['1h', '180d'],
    ['1d', '3y'],
    ['1w', '5y'],
    ['unknown', '90d'],
  ])('maps timeframe %s to history %s', (timeframe, expected) => {
    expect(getDefaultHistoryLookbackByTimeframe(timeframe)).toBe(expected)
  })

  it('normalizes nullable strings and structured values safely', () => {
    expect(toNullableConfigString(undefined)).toBeNull()
    expect(toNullableConfigString('   ')).toBeNull()
    expect(toNullableConfigString(' value ')).toBe('value')
    expect(parseStructuredConfigValue({ size: 2 })).toEqual({ size: 2 })
    expect(parseStructuredConfigValue('{"size":2}')).toEqual({ size: 2 })
    expect(parseStructuredConfigValue(2)).toBeNull()
  })

  it('handles lists, token-only entries, and URLs', () => {
    expect(splitEntries('btc/usdc, \"eth/usdc\"')).toEqual([
      'btc/usdc',
      'eth/usdc',
    ])
    expect(toTokenOnlyEntries('btc/usdc, eth-usdc')).toBe('BTC,ETH')
    expect(toTokenOnlyEntries('https://example.test/pairs')).toBe(
      'https://example.test/pairs',
    )
    expect(normalizePairEntries('https://example.test/pairs', 'USDC')).toBe(
      'https://example.test/pairs',
    )
    expect(normalizePairEntries(null, 'USDC')).toBeNull()
  })

  it('rejects invalid volume inputs and chooses stable suffixes', () => {
    expect(buildVolumeConfig(null)).toBeNull()
    expect(buildVolumeConfig(Number.POSITIVE_INFINITY)).toBeNull()
    expect(buildVolumeConfig(500)).toEqual({ size: 0.5, range: 'K' })
    expect(buildVolumeConfig(2_000_000_000_000)).toEqual({
      size: 2,
      range: 'T',
    })
    expect(parseVolumeLimitToNumber(null)).toBeNull()
    expect(parseVolumeLimitToNumber({ size: 2, range: 'x' })).toBeNull()
  })

  it('builds canonical CSV signal settings', () => {
    const settings = buildSignalSettingsValue({
      signal: 'csv_signal',
      symsignal_url: null,
      symsignal_key: null,
      symsignal_version: null,
      symsignal_allowedsignals: [],
      csvsignal_mode: 'file',
      csvsignal_source: ' signals.csv ',
      csvsignal_inline: null,
    })

    expect(settings).toEqual({
      csv_source: 'signals.csv',
    })
  })

  it('builds canonical SymSignals and websocket settings', () => {
    expect(
      buildSignalSettingsValue({
        signal: 'sym_signals',
        symsignal_url: ' https://signals.test ',
        symsignal_key: ' key ',
        symsignal_version: ' v1 ',
        symsignal_allowedsignals: ['BOT_START'],
        csvsignal_mode: null,
        csvsignal_source: null,
        csvsignal_inline: null,
      }),
    ).toEqual({
      api_url: 'https://signals.test',
      api_key: 'key',
      api_version: 'v1',
      allowed_signals: ['BOT_START'],
    })

    expect(
      buildSignalSettingsValue({
        signal: 'websocket_signal',
        symsignal_url: null,
        symsignal_key: null,
        symsignal_version: null,
        symsignal_allowedsignals: [],
        csvsignal_mode: null,
        csvsignal_source: null,
        csvsignal_inline: null,
        websocket_url: 'wss://signals.test',
        websocket_headers: '{"Authorization":"redacted"}',
        websocket_subscribe_message: '{"type":"subscribe"}',
        websocket_required_decision: 'warn',
        websocket_min_confidence: 0.75,
        websocket_accepted_exchanges: 'binance',
        websocket_accepted_market_states: 'bullish',
      }),
    ).toMatchObject({
      websocket_url: 'wss://signals.test',
      headers: { Authorization: 'redacted' },
      subscribe_message: { type: 'subscribe' },
      required_decision: 'warn',
      min_confidence: 0.75,
      accepted_exchanges: 'binance',
      accepted_market_states: 'bullish',
    })
  })

  it('recognizes websocket URLs and returns null for unknown sources', () => {
    expect(isWebsocketUrl('wss://signals.test')).toBe(true)
    expect(isWebsocketUrl('https://signals.test')).toBe(false)
    expect(isWebsocketUrl(null)).toBe(false)
    expect(
      buildSignalSettingsValue({
        signal: 'asap',
        symsignal_url: null,
        symsignal_key: null,
        symsignal_version: null,
        symsignal_allowedsignals: [],
        csvsignal_mode: null,
        csvsignal_source: null,
        csvsignal_inline: null,
      }),
    ).toBeNull()
  })
})
