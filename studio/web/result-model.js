import { t, getLocale } from './i18n.js';

export function resultDate(created) {
  if (created == null) return null;
  const date = new Date(typeof created === 'number' ? created * 1000 : created);
  return Number.isNaN(date.getTime()) ? null : date;
}

export const resultTime = task => resultDate(task.finished ?? task.created)?.getTime() || 0;
export const resultTimeLabel = task => resultDate(task.finished ?? task.created)?.toLocaleString(getLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) || '';

export function primaryArtifact(artifacts = [], result = null) {
  return artifacts.find(a => a.name === result?.primary && /\.glb$/i.test(a.name)) ||
    artifacts.find(a => a.name === 'scene.glb') ||
    artifacts.find(a => a.name === 'index.html') ||
    artifacts.find(a => !a.name.includes('/') && /\.glb$/i.test(a.name)) ||
    artifacts.find(a => /\.glb$/i.test(a.name)) ||
    artifacts.find(a => /\.(html|png|jpe?g|webp|json|svg)$/i.test(a.name));
}

export function thumbnailArtifact(task) {
  return task.artifacts?.find(a => a.name === task.result?.thumbnail && /\.(png|jpe?g|webp)$/i.test(a.name)) ||
    task.artifacts?.find(a => /^(preview|render)\.(png|jpe?g|webp)$/i.test(a.name));
}

// A successful probe/report is not a model. Keep it in the full task history.
export function recentResults(tasks = []) {
  return tasks.filter(task => task.status === 'completed' && task.category !== 'observation' &&
    !['merge-review', 'a8-review'].includes(task.template) &&
    /\.glb$/i.test(primaryArtifact(task.artifacts, task.result)?.name || ''))
    .sort((a, b) => resultTime(b) - resultTime(a));
}

export function resultGroups(tasks = []) {
  const results = recentResults(tasks), byId = new Map(results.map(t => [t.id, t]));
  const groups = new Map();
  for (const task of results) {
    let root = task, seen = new Set();
    while (root.source_task && byId.has(root.source_task) && !seen.has(root.id)) {
      seen.add(root.id); root = byId.get(root.source_task);
    }
    const id = task.result?.work_id ? `work:${task.result.work_id}` : `task:${root.id}`;
    if (!groups.has(id)) groups.set(id, { id, title: task.result?.work_title || root.title || t('entry.untitled'), tasks: [], latest: [], older: [] });
    const group = groups.get(id), variant = task.result?.variant || '';
    group.tasks.push(task);
    if (!group.latest.some(t => (t.result?.variant || '') === variant)) group.latest.push(task);
    else group.older.push(task);
  }
  return [...groups.values()];
}

export function resultIdentity(task, artifact = primaryArtifact(task.artifacts, task.result)) {
  return {
    title: task.result?.work_title || task.title || t('entry.untitled'),
    detail: [task.result?.variant, task.result?.version, resultTimeLabel(task), artifact?.name].filter(Boolean).join(' · '),
    note: task.result?.note || t('entry.unreviewed'),
  };
}
