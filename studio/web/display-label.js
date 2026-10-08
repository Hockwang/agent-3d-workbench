import { t } from './i18n.js';

// Old task titles and imported animation labels can include implementation
// names. Only format display text: asset names, clip bindings, requests, and
// stored evidence retain their original identifiers and bytes.
const IMPLEMENTATIONS = [
  [/(?<![a-z0-9])(?:unimate|kimodo)(?![a-z0-9])/gi, 'publicLabel.motion'],
  [/(?<![a-z0-9])puppeteer(?![a-z0-9])/gi, 'publicLabel.rigA'],
  [/(?<![a-z0-9])skintokens(?![a-z0-9])/gi, 'publicLabel.rigB'],
  [/(?<![a-z0-9])(?:unirig|riganything)(?![a-z0-9])/gi, 'publicLabel.rig'],
  [/(?<![a-z0-9])(?:p3[-_ ]?sam|p3rw)(?![a-z0-9])/gi, 'publicLabel.segmentA'],
  [/(?<![a-z0-9])cubepart(?![a-z0-9])/gi, 'publicLabel.segmentB'],
  [/(?<![a-z0-9])partcraft(?:er)?(?![a-z0-9])/gi, 'publicLabel.segment'],
];
export function displayLabel(value) {
  if (typeof value !== 'string') return value;
  return IMPLEMENTATIONS.reduce((text, [pattern, key]) => text.replace(pattern, () => t(key)), value);
}
