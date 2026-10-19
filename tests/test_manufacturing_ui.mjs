import test from 'node:test';
import assert from 'node:assert/strict';
import {manufacturingSliceTotals,manufacturingStages} from '../studio/web/manufacturing.js';

test('slice summary requires successful finite receipts from every real plate',()=>{
  assert.equal(manufacturingSliceTotals({}),null);
  assert.equal(manufacturingSliceTotals({check:{plates:[]}}),null);
  assert.equal(manufacturingSliceTotals({check:{plates:[{returncode:1,grams:12,seconds:300}]}}),null);
  assert.equal(manufacturingSliceTotals({check:{plates:[{returncode:0,grams:NaN,seconds:300}]}}),null);
  const result=manufacturingSliceTotals({check:{plates:[{returncode:0,grams:465.41,seconds:24336.890625,warnings:[]},{returncode:0,grams:10,seconds:300,warnings:['unstable base']}]}});
  assert.deepEqual(result,{grams:475.41,seconds:24636.890625,plates:2,warnings:1});
});

test('the future repair API has no executable stage',()=>{
  assert(!manufacturingStages.includes('repair_api'));
  assert(manufacturingStages.includes('local_repair'));
});
