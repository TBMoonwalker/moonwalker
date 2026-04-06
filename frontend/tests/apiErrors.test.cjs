const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { extractApiErrorMessage } = loadFrontendModule('src/helpers/apiErrors.ts')

test('extractApiErrorMessage prefers backend message over other fields', () => {
    const message = extractApiErrorMessage(
        {
            isAxiosError: true,
            message: 'Request failed with status code 409',
            response: {
                data: {
                    message: 'Live activation blocked until setup is complete.',
                    error: 'blocked',
                },
            },
        },
        'fallback',
    )

    assert.equal(message, 'Live activation blocked until setup is complete.')
})

test('extractApiErrorMessage falls back to backend error and serialized payloads', () => {
    assert.equal(
        extractApiErrorMessage(
            {
                isAxiosError: true,
                response: {
                    data: {
                        error: 'Backup restore failed.',
                    },
                },
            },
            'fallback',
        ),
        'Backup restore failed.',
    )

    assert.equal(
        extractApiErrorMessage(
            {
                response: {
                    data: {
                        blockers: [{ key: 'secret' }],
                    },
                },
            },
            'fallback',
        ),
        JSON.stringify({
            blockers: [{ key: 'secret' }],
        }),
    )
})

test('extractApiErrorMessage falls back to transport and generic errors', () => {
    assert.equal(
        extractApiErrorMessage(
            {
                isAxiosError: true,
                message: 'Network Error',
            },
            'fallback',
        ),
        'Network Error',
    )

    assert.equal(
        extractApiErrorMessage(new Error('Request failed'), 'fallback'),
        'Request failed',
    )
    assert.equal(extractApiErrorMessage(null, 'fallback'), 'fallback')
})
