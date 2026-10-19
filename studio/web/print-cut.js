import { t } from './i18n.js';

// Bind recovery to the exact loaded print copy, including file versions and printer.
export const printCopyStamp = state => JSON.stringify([
  state?.printer?.name, state?.print_sources,
  state?.parts?.map(p => [p.name, p.stl_url]),
]);

export function cutSource(state, partName) {
  const index = state?.parts?.findIndex(p => p.name === partName) ?? -1;
  if (index < 0 || !state.print_sources?.[index] || state.parts.length !== state.print_sources.length) {
    throw new Error(t('printFit.sourceMissing'));
  }
  return { name: partName, index, files: [...state.print_sources], printer: state.printer?.name,
    stamp: printCopyStamp(state), knownIds: [] };
}

export const cutIds = (context, state) => (state?.objects || []).filter(o => context.knownIds.includes(o.id)).map(o => o.id);

// Recovery is a focused view, not a visibility edit to the user's saved scene.
// The viewport, object list and selection must all use this same projection.
export function cutView(context, state) {
  if (!context || !state) return state;
  const ids = new Set(cutIds(context, state));
  return { ...state, objects: state.objects.filter(o => ids.has(o.id)),
    selection: state.selection.filter(id => ids.has(id)) };
}

// Keep old IDs too: editor undo/redo restores them. Only descendants of this
// recovery's selection belong to the replacement; unrelated scene objects never do.
export function trackCut(context, before, after, action, params = {}) {
  if (!context || ['open', 'undo', 'redo', 'import', 'primitive'].includes(action)) return;
  const selected = params.ids || before.selection || [];
  if (!selected.length || !selected.every(id => context.knownIds.includes(id))) return;
  const old = new Set(before.objects.map(o => o.id));
  context.knownIds = [...new Set([...context.knownIds, ...after.objects.filter(o => !old.has(o.id)).map(o => o.id)])];
}

export function replacementFiles(context, state, newFiles) {
  if (context.stamp !== printCopyStamp(state)) throw new Error(t('printFit.sourceChanged'));
  if (!newFiles?.length) throw new Error(t('printFit.noPieces'));
  return context.files.flatMap((file, i) => i === context.index ? newFiles : [file]);
}
