const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    buildLiveRegionAnnouncement,
    deriveGuidedFocusTarget,
} = loadFrontendModule('src/control-center/focusFlow.ts')

test('deriveGuidedFocusTarget maps targets to stable workspace anchors', () => {
    const signalTarget = deriveGuidedFocusTarget('signal')
    const dcaTarget = deriveGuidedFocusTarget('dca')

    assert.deepEqual(signalTarget, {
        announcement: 'Signal source opened.',
        sectionId: 'control-center-signal',
        title: 'Signal source',
    })
    assert.deepEqual(dcaTarget, {
        announcement: 'Trade modes opened.',
        sectionId: 'control-center-dca',
        title: 'Trade modes',
    })
})

test('buildLiveRegionAnnouncement reuses transition copy for polite announcements', () => {
    const message = buildLiveRegionAnnouncement({
        kind: 'restore',
        status: 'success',
        message: 'Restore completed successfully.',
        at: Date.now(),
        mode: 'overview',
    })

    assert.equal(message, 'Restore completed successfully.')
})
