const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

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
const configViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Config.vue'),
    'utf8',
)
const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const setupModeSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupMode.vue',
    ),
    'utf8',
)

test('dry-run exchange control stays on the guarded live-activation path', () => {
    assert.match(exchangeSectionSource, /dryRunActivationLocked: boolean/)
    assert.match(exchangeSectionSource, /:disabled="dryRunActivationLocked"/)
    assert.match(
        exchangeSectionSource,
        /Activate live trading from Overview after saving the rest of/,
    )
    assert.match(
        configViewSource,
        /:dry-run-activation-locked="baselineState\?\.exchange\?\.dry_run === true"/,
    )
    assert.match(setupModeSource, /dryRunActivationLocked: boolean/)
    assert.match(
        setupModeSource,
        /:dry-run-activation-locked="dryRunActivationLocked"/,
    )
    assert.match(controlCenterViewSource, /baselineState,/
    )
    assert.match(
        controlCenterViewSource,
        /:dry-run-activation-locked="\s*baselineState\?\.exchange\?\.dry_run === true\s*"/,
    )
})
