const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const generalSectionSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'config', 'ConfigGeneralSection.vue'),
    'utf8',
)
const advancedGeneralSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigGeneralAdvancedSection.vue',
    ),
    'utf8',
)

test('general config surfaces expose AI Trust Ollama settings', () => {
    for (const source of [generalSectionSource, advancedGeneralSectionSource]) {
        assert.match(source, /AI Trust Cockpit enabled/)
        assert.match(source, /ai_trust_enabled/)
        assert.match(source, /Block AI warning entries/)
        assert.match(source, /ai_trust_enforce_warnings/)
        assert.match(source, /Ollama base URL/)
        assert.match(source, /ai_trust_ollama_base_url/)
        assert.match(source, /Ollama model/)
        assert.match(source, /ai_trust_ollama_model/)
        assert.match(source, /AI timeout \(ms\)/)
        assert.match(source, /ai_trust_timeout_ms/)
        assert.match(source, /AI retry budget/)
        assert.match(source, /ai_trust_max_retries/)
        assert.doesNotMatch(source, /api[_ -]?key/i)
    }
})
