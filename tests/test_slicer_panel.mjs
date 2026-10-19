import test from 'node:test';
import assert from 'node:assert/strict';
import { Panel } from '../studio/web/panel.js';

// Minimal native-select semantics: assigning a missing option clears the value.
class Select {
  tagName = 'SELECT';
  options = [];
  selected = '';
  get value() { return this.options.some(o => o.value === this.selected) ? this.selected : ''; }
  set value(value) { this.selected = this.options.some(o => o.value === value) ? value : ''; }
  appendChild(option) {
    this.options.push(option);
    if (this.options.length === 1) this.selected = option.value;
  }
  replaceChildren() { this.options = []; this.selected = ''; }
  set innerHTML(value) { assert.equal(value, ''); this.replaceChildren(); }
}

function fixture(t) {
  const original = globalThis.document;
  const nodes = Object.fromEntries(['slicer-select', 'printer-source', 'printer-vendor', 'printer-select'].map(id => [id, new Select()]));
  nodes['printer-catalog-summary'] = {};
  for (const value of ['bambu', 'orca']) nodes['printer-source'].appendChild({value});
  globalThis.document = {getElementById: id => nodes[id], createElement: () => ({value: '', textContent: ''})};
  t.after(() => { globalThis.document = original; });
  const panel = Object.create(Panel.prototype);
  panel._printers = [];
  panel._renderPrinterRow = () => {};
  panel._renderSlicerHint = () => {};
  return {panel, nodes};
}

const printers = [
  {name: 'Bambu Lab P1S 0.4 nozzle', slicer: 'bambu', vendor: 'BBL'},
  {name: 'elegoo::Elegoo::Neptune', slicer: 'elegoo', vendor: 'Elegoo'},
];
const slicers = ['bambu', 'elegoo'].map(id => ({id, name: id, installed: true, automated_profiles: true, headless_slice: true}));

test('existing job received before catalogs retains its slicer and printer after initialization', t => {
  const {panel, nodes} = fixture(t);
  panel._lastState = {printer: {name: printers[1].name, slicer: 'elegoo'}};
  panel.setPrinters(printers);
  panel.setSlicers(slicers);
  assert.equal(nodes['printer-source'].value, 'elegoo');
  assert.equal(nodes['printer-select'].value, printers[1].name);
});

test('mock printer catalog without slicer metadata remains selectable', t => {
  const {panel, nodes} = fixture(t);
  panel.setPrinters(printers.slice(0, 1));
  panel.setSlicers([]);
  assert.equal(nodes['printer-source'].value, 'bambu');
  assert.equal(nodes['printer-select'].value, printers[0].name);
});
