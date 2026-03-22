const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    buildSetupEntryChoiceHistoryState,
    CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY,
    getSetupEntryChoiceFromHistoryState,
    parseSetupEntryChoice,
} = loadFrontendModule('src/control-center/setupEntryHistory.ts')

test('parseSetupEntryChoice accepts known choices only', () => {
    assert.equal(parseSetupEntryChoice('restore'), 'restore')
    assert.equal(parseSetupEntryChoice('new'), 'new')
    assert.equal(parseSetupEntryChoice('guided'), null)
    assert.equal(parseSetupEntryChoice(null), null)
})

test('getSetupEntryChoiceFromHistoryState reads known history state values', () => {
    assert.equal(
        getSetupEntryChoiceFromHistoryState({
            [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'restore',
        }),
        'restore',
    )
    assert.equal(
        getSetupEntryChoiceFromHistoryState({
            [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'unknown',
        }),
        null,
    )
    assert.equal(getSetupEntryChoiceFromHistoryState(null), null)
})

test('buildSetupEntryChoiceHistoryState merges and clears the entry choice key', () => {
    const mergedState = buildSetupEntryChoiceHistoryState(
        {
            step: 'setup',
            [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'restore',
        },
        'new',
    )

    assert.deepEqual(mergedState, {
        step: 'setup',
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'new',
    })

    const clearedState = buildSetupEntryChoiceHistoryState(mergedState, null)
    assert.deepEqual(clearedState, {
        step: 'setup',
    })
})
