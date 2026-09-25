import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
   getEffectiveCss,
   NAIVE_CSS_PAIRS,
   themeTokens,
   type ColorScheme,
} from '../src/theme/tokens'

/**
 * Build-time drift guard.
 *
 * `src/theme/tokens.ts` is the single source of truth for the design system.
 * Two layers mirror it at runtime:
 *   1. the Naive UI `themeOverrides` (consumed by `App.vue`), and
 *   2. the CSS custom properties in `assets/base.css` (`--mw-*`, `--color-*`).
 *
 * This test parses `base.css` and asserts both layers stay in agreement, so a
 * token changed in one layer fails CI until the other is updated in lockstep.
 * This is exactly the class of bug the T8 light-muted AA fix introduced: the
 * CSS `--mw-color-text-muted` was updated but the Naive `textColor3` was not.
 */

// Vitest runs with cwd === the `frontend/` package root, so resolve relative to
// it (a `file://` import.meta URL isn't available under the jsdom environment).
const BASE_CSS = resolve(process.cwd(), 'src', 'assets', 'base.css')

/** Return the inner text of the brace-balanced block that opens at/after `from`. */
function braceGroup(text: string, from: number): string {
   const open = text.indexOf('{', from)
   if (open < 0) {
      throw new Error('missing opening brace')
   }
   let depth = 0
   for (let i = open; i < text.length; i++) {
      const ch = text[i]
      if (ch === '{') {
         depth++
      } else if (ch === '}') {
         depth--
         if (depth === 0) {
            return text.slice(open + 1, i)
         }
      }
   }
   throw new Error('unbalanced braces')
}

/** Parse `--name: value;` declarations out of a CSS block body. */
function declarationsOf(body: string): Record<string, string> {
   const out: Record<string, string> = {}
   const re = /--([A-Za-z0-9-]+)\s*:\s*([^;]+);/g
   let match: RegExpExecArray | null
   while ((match = re.exec(body)) !== null) {
      out[`--${match[1].trim()}`] = match[2].trim()
   }
   return out
}

/** Normalize cosmetic whitespace so only meaningful drift is flagged. */
const normalize = (value: string | undefined): string =>
   (value ?? '')
      .trim()
      .replace(/\s*,\s*/g, ',')
      .replace(/\s{2,}/g, ' ')

const cssText = readFileSync(BASE_CSS, 'utf8')

// Light baseline: the first top-level `:root` block.
const lightBody = braceGroup(cssText, cssText.indexOf(':root'))
const parsedLight = declarationsOf(lightBody)

// Dark overrides: the `:root` nested inside the prefers-color-scheme query.
const mediaIndex = cssText.indexOf('@media (prefers-color-scheme: dark)')
const mediaBody = braceGroup(cssText, mediaIndex)
const darkBody = braceGroup(mediaBody, mediaBody.indexOf(':root'))
const parsedDark = declarationsOf(darkBody)

// Forced dark (T1 Phase 3): a top-level [data-mw-theme="dark"] block retheme
// dark even when the OS is light. It must hold the SAME dark values as the
// auto-dark media block above, so a forced selection and the OS-auto path can
// never drift apart.
const forcedDarkIndex = cssText.indexOf(':root[data-mw-theme="dark"]')
const parsedForcedDark =
    forcedDarkIndex >= 0
        ? declarationsOf(braceGroup(cssText, forcedDarkIndex))
        : {}

function expectLayerMirrorsMap(
   label: string,
   parsed: Record<string, string>,
   source: Record<string, string>,
): void {
   const parsedKeys = Object.keys(parsed).sort()
   const sourceKeys = Object.keys(source).sort()
   // Bidirectional: flags both base.css drift AND map drift.
   expect(parsedKeys).toEqual(sourceKeys)
   for (const key of sourceKeys) {
      expect(normalize(parsed[key])).toBe(normalize(source[key]))
   }
   // No stray, un-parsed declaration should survive in the layer.
   expect(parsedKeys.length).toBeGreaterThan(0)
 }

function checkNaivePairs(scheme: ColorScheme): void {
   const effective = getEffectiveCss(scheme)
   for (const { naive, css } of NAIVE_CSS_PAIRS) {
      const cssValue = effective[css]
      expect(cssValue, `missing CSS token ${css} for ${scheme}`).not.toBeUndefined()
      expect(normalize(cssValue)).toBe(
         normalize(themeTokens[scheme].naive.common[naive]),
      )
   }
}

describe('theme drift guard', () => {
   it('base.css :root mirrors themeTokens.light.css exactly', () => {
      expectLayerMirrorsMap('light', parsedLight, themeTokens.light.css)
   })

   it('base.css @media dark :root mirrors themeTokens.dark.css exactly', () => {
      expectLayerMirrorsMap('dark', parsedDark, themeTokens.dark.css)
   })

   it('Naive overrides track the mapped CSS tokens for light', () => {
      checkNaivePairs('light')
   })

   it('Naive overrides track the mapped CSS tokens for dark', () => {
      checkNaivePairs('dark')
   })

   it('base.css [data-mw-theme="dark"] mirrors themeTokens.dark.css exactly', () => {
     expect(
      forcedDarkIndex,
       'the forced-dark attribute block is missing from base.css',
      ).toBeGreaterThanOrEqual(0)
     expectLayerMirrorsMap('forced-dark', parsedForcedDark, themeTokens.dark.css)
    })

   it('no dedicated forced-light block — light is the CSS baseline', () => {
     // Forced light is achieved by the auto-dark media's :not([data-mw-theme])
     // guard + the light baseline, not a second block; a stray forced-light
     // block would bypass that intent, so its absence is asserted here.
     expect(
      cssText.indexOf(':root[data-mw-theme="light"]'),
      'a forced-light block would bypass the light-baseline design',
      ).toBe(-1)
    })
})
