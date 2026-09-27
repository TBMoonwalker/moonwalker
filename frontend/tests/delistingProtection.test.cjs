const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const exchangeSectionSource = fs.readFileSync(
     path.join(
          __dirname,
          '..',
          'src',
          'components',
          'config',
          'ConfigExchangeSection.vue',
     ),
     'utf8',
)
const signalSectionSource = fs.readFileSync(
     path.join(
          __dirname,
          '..',
          'src',
          'components',
          'config',
          'ConfigSignalSection.vue',
     ),
     'utf8',
)
const openTradeColumnsSource = fs.readFileSync(
     path.join(
          __dirname,
          '..',
          'src',
          'composables',
          'useOpenTradeColumns.ts',
     ),
     'utf8',
)

const capability = loadFrontendModule('src/helpers/delistingCapability.ts')

test('exchange settings own the delisting protection setting', () => {
     assert.match(exchangeSectionSource, /Protect against delisting/)
     assert.match(
          exchangeSectionSource,
           /v-model:value="exchange\.delisting_protection_enabled"/,
     )
     assert.match(
          exchangeSectionSource,
           /v-model:value="\s*exchange\.delisting_schedule_use_trading_credentials\s*"/,
     )
     assert.match(
          exchangeSectionSource,
           /Use trading API credentials/,
     )
     assert.match(
          exchangeSectionSource,
            /v-model:value="exchange\.delisting_schedule_api_key"/,
     )
     assert.match(exchangeSectionSource, /Binance schedule credentials/)
     assert.match(
          exchangeSectionSource,
            /v-model:value="exchange\.delisting_schedule_api_secret"/,
     )
})

test('delisting protection is exchange-aware and hidden for unsupported exchanges', () => {
     // The block only renders when the selected exchange has a supported
     // schedule source; otherwise nothing shows.
     assert.match(
          exchangeSectionSource,
           /v-if="delistingKind !== 'none'"/,
     )
     assert.match(
          exchangeSectionSource,
            /delistingScheduleKindForExchange\(exchange\.name\)/,
     )
     assert.match(
          exchangeSectionSource,
           /helpers\/delistingCapability/,
       )
     // A dedicated branch exists for the Bybit public feed (no credentials).
     assert.match(exchangeSectionSource, /title="Bybit schedule source"/)
     // The delisting setting must not leak back into Signal settings.
     assert.doesNotMatch(signalSectionSource, /delisting_protection_enabled/)
})

test('delisting schedule capability resolves per exchange', () => {
     assert.equal(capability.delistingScheduleKindForExchange('binance'), 'binance')
     assert.equal(capability.delistingScheduleKindForExchange('bybit'), 'bybit')
     assert.equal(capability.delistingScheduleKindForExchange('bybiteu'), 'bybit')
     assert.equal(
          capability.delistingScheduleKindForExchange('Kraken'),
           'none',
     )
     assert.equal(capability.delistingScheduleKindForExchange(''), 'none')
     assert.equal(capability.delistingScheduleKindForExchange(null), 'none')
     assert.equal(capability.exchangeSupportsDelistingProtection('binance'), true)
     assert.equal(
          capability.exchangeSupportsDelistingProtection('kraken'),
           false,
       )
})

test('delisting protection descriptions mention exits and Bybit degradation', () => {
     assert.match(
          capability.DELISTING_PROTECTION_DESCRIPTION.binance,
           /Existing exits remain enabled\./,
       )
     assert.match(
          capability.DELISTING_PROTECTION_DESCRIPTION.bybit,
           /Existing exits remain enabled\./,
       )
     assert.match(
          capability.DELISTING_PROTECTION_DESCRIPTION.bybit,
            /never blocks trading/i,
     )
     assert.equal(capability.DELISTING_PROTECTION_DESCRIPTION.none, '')
})

test('open trade table marks delisting risk and disables manual buys', () => {
     assert.match(openTradeColumnsSource, /Boolean\(rowData\.delisting_warning\)/)
     assert.match(openTradeColumnsSource, /Delisting risk/)
     assert.match(openTradeColumnsSource, /Scheduled for delisting at/)
     assert.match(openTradeColumnsSource, /rowData\.delisting_check_unavailable/)
})
