import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { compileLegacyTestImports } from '../knip'

const filename = resolve(import.meta.dirname, '../tests/example.test.cjs')

describe('Knip legacy loader compiler', () => {
  it('preserves named accesses while resolving literal module paths', () => {
    const source = "const { readText } = loadFrontendModule(\n 'src/helpers/safeStorage.ts',\n)"
    expect(compileLegacyTestImports(source, filename)).toBe(
      'const { readText } = require("../src/helpers/safeStorage.ts")',
    )
  })

  it('resolves multiple calls relative to nested test files', () => {
    const nested = resolve(import.meta.dirname, '../tests/nested/example.test.cjs')
    const source = "loadFrontendModule('src/config.ts'); loadFrontendModule('src/main.ts')"
    expect(compileLegacyTestImports(source, nested)).toBe(
      'require("../../src/config.ts"); require("../../src/main.ts")',
    )
  })

  it('leaves dynamic paths, comments and unrelated function calls untouched', () => {
    const source = "// loadFrontendModule('src/main.ts')\nloadFrontendModule(path); other('src/main.ts')"
    expect(compileLegacyTestImports(source, filename)).toBe(source)
  })

  it('handles qualified loader calls and leading slash paths used by legacy tests', () => {
    const source = "const { parseMonitoringLogLevel } = require('./helpers/loadFrontendModule.cjs').loadFrontendModule('/src/helpers/monitoringLogs.ts')"
    expect(compileLegacyTestImports(source, filename)).toBe(
      'const { parseMonitoringLogLevel } = require("../src/helpers/monitoringLogs.ts")',
    )
  })

  it('exposes namespace property usages through an ordinary namespace import', () => {
    const source = "const capability = loadFrontendModule('src/helpers/delistingCapability.ts'); capability.exchangeSupportsDelistingProtection('binance')"
    expect(compileLegacyTestImports(source, filename)).toBe(
      'import * as capability from "../src/helpers/delistingCapability.ts"; capability.exchangeSupportsDelistingProtection(\'binance\')',
    )
  })
})
