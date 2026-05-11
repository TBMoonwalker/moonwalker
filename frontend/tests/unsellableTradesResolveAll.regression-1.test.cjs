const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const unsellableTradesSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'UnsellableTrades.vue'),
    'utf8',
)

test('unsellable trades surface exposes bulk resolve controls', () => {
    assert.ok(
        unsellableTradesSource.includes('Resolve all'),
        'expected the unsellable trades table to expose a resolve-all action',
    )
    assert.ok(
        unsellableTradesSource.includes('/trades/unsellable/delete/all'),
        'expected the resolve-all action to call the bulk unsellable delete endpoint',
    )
    assert.ok(
        unsellableTradesSource.includes("title: 'Resolve all unsellable trades'"),
        'expected the bulk resolve action to confirm intent before clearing the list',
    )
    assert.ok(
        unsellableTradesSource.includes('syncUnsellableRows([])'),
        'expected the bulk resolve action to update the live table state immediately',
    )
})
