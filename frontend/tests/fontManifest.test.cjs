const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

// Self-hosted font manifest (2026-11-25 design review DV-1..DV-6): the
// vendored woff2 files, the @font-face rules in fonts.css, and the no-CDN
// guarantee in base.css must stay in lockstep. The e2e font-face spec only
// exercises the 9 faces the dashboard renders in Latin; this static check
// pins the full 37-rule manifest, including the non-Latin subset files the
// e2e run never fetches.
//
// Value: protects=fonts.css 37-rule manifest lockstep with the vendored
// woff2 files, the 9-face e2e contract, and the no-remote-import invariant;
// fails_when=a rule or file drifts (missing src, orphan woff2, dropped swap,
// a vendored 450, a re-added remote @import); why_new=the e2e font spec only
// fetches the Latin faces the desktop renders, so the 28 non-Latin subset
// rules and the no-CDN guarantee had no guard; seam=none; no_claim=static
// parse only - rendered behavior is the e2e font gate's job.

const FONTS_DIR = path.join(__dirname, '..', 'src', 'assets', 'fonts')
const FONTS_CSS = path.join(FONTS_DIR, 'fonts.css')
const BASE_CSS = path.join(__dirname, '..', 'src', 'assets', 'base.css')

const DECLARED_FACES = new Set([
    ['Inter', '400'],
    ['Inter', '500'],
    ['Inter', '600'],
    ['Inter', '700'],
    ['IBM Plex Mono', '400'],
    ['IBM Plex Mono', '500'],
    ['Source Sans 3', '400'],
    ['Source Sans 3', '500'],
    ['Source Sans 3', '600'],
].map(([family, weight]) => `${family}@${weight}`))

function parseFontFaceRules(css) {
    const rules = []
    const rulePattern = /@font-face\s*\{([^}]*)\}/g
    for (const match of css.matchAll(rulePattern)) {
        const body = match[1]
        const prop = (name) => {
            const found = body.match(new RegExp(`${name}\\s*:\\s*([^;]+)`, 'i'))
            return found ? found[1].trim() : null
        }
        rules.push({
            family: prop('font-family'),
            weight: prop('font-weight'),
            display: prop('font-display'),
            srcs: [...body.matchAll(/url\(\s*['"]?([^'")\s]+)['"]?\s*\)/g)].map((src) => src[1]),
        })
    }
    return rules
}

function listWoff2Files(dir) {
    const found = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            found.push(...listWoff2Files(full))
        } else if (entry.name.endsWith('.woff2')) {
            found.push(full)
        }
    }
    return found
}

test('fonts.css manifest stays in lockstep with the vendored woff2 files', () => {
    const css = fs.readFileSync(FONTS_CSS, 'utf8')
    const rules = parseFontFaceRules(css)
    assert.equal(rules.length, 37, 'font-face rule count drifted from the pinned 37-rule manifest')

    const referenced = new Set()
    for (const rule of rules) {
        assert.equal(
            rule.display,
            'swap',
            `missing font-display: swap on ${rule.family} ${rule.weight} (first-paint behavior would drift)`,
        )
        assert.notEqual(
            rule.weight,
            '450',
            'a 450 face was vendored; IBM Plex Mono has no 450 face and legacy 450 declarations render at 500 (DESIGN.md pins 500)',
        )
        assert.ok(rule.srcs.length === 1, `expected one src per rule, got ${rule.srcs.length}`)
        for (const src of rule.srcs) {
            assert.ok(src.startsWith('./'), `unexpected src reference in fonts.css: ${src}`)
            const file = path.resolve(FONTS_DIR, src)
            referenced.add(path.relative(FONTS_DIR, file))
            assert.ok(fs.existsSync(file), `fonts.css references a missing file: ${src}`)
        }
    }

    const faces = new Set(
        rules.map((rule) => `${String(rule.family).replace(/^'(.*)'$/, '$1')}@${rule.weight}`),
    )
    assert.deepEqual(
        [...faces].sort(),
        [...DECLARED_FACES].sort(),
        'declared face set drifted from the 9-face e2e contract',
    )

    const orphans = listWoff2Files(FONTS_DIR)
        .map((file) => path.relative(FONTS_DIR, file))
        .filter((file) => !referenced.has(file))
    assert.deepEqual(
        orphans,
        [],
        `vendored woff2 files no longer referenced by fonts.css: ${orphans.join(', ')}`,
    )
})

test('base.css and fonts.css keep no remote font imports', () => {
    for (const file of [BASE_CSS, FONTS_CSS]) {
        const css = fs.readFileSync(file, 'utf8')
        const remote = [...css.matchAll(/@import\s+url\(\s*['"]?https?:|url\(\s*['"]?https?:/g)]
        assert.deepEqual(
            remote,
            [],
            `remote font URL found in ${path.basename(file)}; fonts must be self-hosted`,
        )
    }
})
