import { dirname, relative, resolve } from 'node:path'
import ts from 'typescript'
import type { KnipConfig } from 'knip'

/** Expose the legacy test loader's literal module paths to static analysis. */
export function compileLegacyTestImports(source: string, filename: string): string {
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true)
  const replacements: { start: number; end: number; text: string }[] = []
  const frontendRoot = resolve(import.meta.dirname)

  function visit(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ((ts.isIdentifier(node.expression) &&
        node.expression.text === 'loadFrontendModule') ||
        (ts.isPropertyAccessExpression(node.expression) &&
          node.expression.name.text === 'loadFrontendModule')) &&
      node.arguments.length === 1 &&
      ts.isStringLiteral(node.arguments[0]) &&
      /^\/?src\//.test(node.arguments[0].text)
    ) {
      const target = resolve(frontendRoot, node.arguments[0].text.replace(/^\//, ''))
      const specifier = relative(dirname(filename), target).replaceAll('\\', '/')
      const modulePath = JSON.stringify(
        specifier.startsWith('.') ? specifier : `./${specifier}`,
      )
      const declaration = node.parent
      if (
        ts.isVariableDeclaration(declaration) &&
        ts.isIdentifier(declaration.name) &&
        ts.isVariableDeclarationList(declaration.parent) &&
        declaration.parent.declarations.length === 1 &&
        ts.isVariableStatement(declaration.parent.parent)
      ) {
        const statement = declaration.parent.parent
        replacements.push({
          start: statement.getStart(tree),
          end: statement.end,
          text: `import * as ${declaration.name.text} from ${modulePath};`,
        })
        return
      }
      replacements.push({
        start: node.getStart(tree),
        end: node.end,
        text: `require(${modulePath})`,
      })
    }
    ts.forEachChild(node, visit)
  }

  visit(tree)
  for (const replacement of replacements.reverse()) {
    source = source.slice(0, replacement.start) +
      replacement.text + source.slice(replacement.end)
  }
  return source
}

export default {
  // Vite, Vitest and Playwright discover their configured entrypoints.
  entry: ['tests/**/*.test.cjs'],
  project: [
    'src/**/*.{ts,tsx,js,vue}',
    'tests/**/*.cjs',
    'tests-vitest/**/*.ts',
    'tests-e2e/**/*.ts',
    '*.config.{ts,mts}',
  ],
  compilers: { cjs: compileLegacyTestImports },
} satisfies KnipConfig
