import test from 'node:test';
import assert from 'node:assert/strict';
import { metricResult } from '../studio/web/evaluation-metrics.js';
test('missing evidence, zero results and errors stay distinct', () => {
  assert.equal(metricResult({pass_rate:null,mean:null,not_evaluated_count:2}), 'NOT_EVALUATED');
  assert.equal(metricResult({pass_rate:0,mean:0,unit:'ratio'}), '通过率 0.0% · 均值 0.0%');
  assert.equal(metricResult({error_count:2}), 'ERROR');
});
test('C0 values and ungraded observations are not presented as pass rates', () => {
  assert.equal(metricResult({value:2,status:'REVIEW'}), '2');
  assert.equal(metricResult({value:false,status:'FAIL'}), '否');
  assert.equal(metricResult({value:.25,unit:'ratio'}), '25.0%');
  assert.equal(metricResult({true_rate:1,graded_count:0}), '成立率 100.0%');
});
