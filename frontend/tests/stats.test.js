// node frontend/tests/stats.test.js
const assert = require('assert'); const s = require('../js/stats.js');
assert.strictEqual(s.median([1, 2, 3, 4]), 2.5); assert.strictEqual(s.quantile([1, 2, 3, 4, 5], 0.25), 2);
assert.strictEqual(s.median([]), null); assert.strictEqual(s.mean([null, 2, 4]), 3);
const sp = s.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]); assert(Math.abs(sp.rho - 1) < 1e-9);
assert(Math.abs(s.spearman([1, 2, 3, 4], [4, 3, 2, 1]).rho + 1) < 1e-9);
assert.strictEqual(s.spearman([1, 2], [1, 2]).rho, null);
assert(Math.abs(s.spearman([1, 2, 2, 3], [1, 3, 2, 4]).rho - 0.9486832980505138) < 1e-9, 'ties');
const b = s.box([1, 2, 3, 4, 5, 100]); assert.strictEqual(b.outliers[0], 100); assert.strictEqual(b.wHi, 5);
const t = s.ticks(0, 575, 5); assert(t[0] === 0 && t[t.length - 1] >= 575);
console.log('stats OK', t.join(','));
