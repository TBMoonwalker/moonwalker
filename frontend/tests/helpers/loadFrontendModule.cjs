const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const Module = require('node:module')

const ts = require('typescript')

const FRONTEND_ROOT = path.resolve(__dirname, '..', '..')
const CACHE_ROOT = fs.mkdtempSync(
    path.join(os.tmpdir(), 'moonwalker-frontend-tests-'),
)
const COMPILED_MODULES = new Map()

const nodePathEntries = [
    path.join(FRONTEND_ROOT, 'node_modules'),
    process.env.NODE_PATH,
].filter(Boolean)
process.env.NODE_PATH = Array.from(new Set(nodePathEntries)).join(
    path.delimiter,
)
Module._initPaths()

function normalizeModulePath(relativePath) {
    return relativePath.startsWith('/') ? relativePath.slice(1) : relativePath
}

function resolveSourcePath(relativePath) {
    return path.join(FRONTEND_ROOT, normalizeModulePath(relativePath))
}

function resolveCompiledPath(sourcePath) {
    const relativePath = path.relative(FRONTEND_ROOT, sourcePath)
    return path.join(CACHE_ROOT, relativePath).replace(/\.[^.]+$/, '.js')
}

function resolveLocalImport(sourcePath, specifier) {
    const basePath = path.resolve(path.dirname(sourcePath), specifier)
    const candidates = [
        basePath,
        `${basePath}.ts`,
        `${basePath}.tsx`,
        `${basePath}.js`,
        `${basePath}.jsx`,
        path.join(basePath, 'index.ts'),
        path.join(basePath, 'index.tsx'),
        path.join(basePath, 'index.js'),
        path.join(basePath, 'index.jsx'),
    ]

    return (
        candidates.find(
            (candidate) =>
                fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
        ) || null
    )
}

function compileModule(sourcePath) {
    const cached = COMPILED_MODULES.get(sourcePath)
    if (cached) {
        return cached
    }

    const sourceText = fs.readFileSync(sourcePath, 'utf8')
    const compiledPath = resolveCompiledPath(sourcePath)

    COMPILED_MODULES.set(sourcePath, compiledPath)

    const { importedFiles } = ts.preProcessFile(sourceText, true, true)
    for (const importedFile of importedFiles) {
        if (!importedFile.fileName.startsWith('.')) {
            continue
        }

        const dependencyPath = resolveLocalImport(
            sourcePath,
            importedFile.fileName,
        )
        if (dependencyPath) {
            compileModule(dependencyPath)
        }
    }

    const result = ts.transpileModule(sourceText, {
        compilerOptions: {
            target: ts.ScriptTarget.ES2022,
            module: ts.ModuleKind.CommonJS,
            moduleResolution: ts.ModuleResolutionKind.Node10,
            jsx: ts.JsxEmit.Preserve,
            esModuleInterop: true,
            allowSyntheticDefaultImports: true,
        },
        fileName: sourcePath,
    })

    fs.mkdirSync(path.dirname(compiledPath), { recursive: true })
    fs.writeFileSync(compiledPath, result.outputText, 'utf8')

    return compiledPath
}

function loadFrontendModule(relativePath) {
    const sourcePath = resolveSourcePath(relativePath)
    const compiledPath = compileModule(sourcePath)
    delete require.cache[compiledPath]
    return require(compiledPath)
}

module.exports = {
    loadFrontendModule,
}
