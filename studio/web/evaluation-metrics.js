// Format platform aggregates without turning missing evidence into zero or a pass.
import { t } from "./i18n.js";

export function metricResult(m) {
  const percent = n => `${(n * 100).toFixed(1)}%`;
  const values = [];
  if (m.pass_rate != null) values.push(t('metrics.passRate', { value: percent(m.pass_rate) }));
  if (m.mean != null) values.push(t('metrics.mean', { value: m.unit === 'ratio' ? percent(m.mean) : m.mean }));
  if (m.value != null) values.push(typeof m.value === 'boolean' ? (m.value ? t('common.yes') : t('common.no')) : m.unit === 'ratio' ? percent(m.value) : String(m.value));
  if (!values.length && m.true_rate != null) values.push(t('metrics.trueRate', { value: percent(m.true_rate) }));
  if (!values.length) return m.status || (m.error_count > 0 ? 'ERROR' : 'NOT_EVALUATED');
  return values.join(' · ');
}
