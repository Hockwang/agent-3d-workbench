// Selection is a small reference snapshot; geometry stays in the shared backend.
import { t } from "../web/i18n.js";

export function selectionContext(mode, state, motion) {
  if (!state || !['edit', 'motion', 'print'].includes(mode)) return null;
  const editing = mode === 'edit' || mode === 'motion';
  const source = editing ? state.workbench : state;
  const objects = new Map((editing ? source?.objects : state.parts)?.map(o => [editing ? o.id : o.name, o]) || []);
  const ids = editing ? source?.selection : state.selection?.parts;
  const selected = [...new Set(ids || [])].map(id => objects.get(id)).filter(Boolean).map(o => ({
    ...(editing ? { id: o.id } : {}), name: o.name,
    ...(o.faces == null ? {} : { faces: o.faces }),
    ...(o.scene ? { instance: { asset: o.scene.asset, family: o.scene.family, kind: o.scene.kind,
      version: o.version, transform: o.transform, bones: o.scene.bones, clips: o.scene.clips } } : {}),
    ...(o.city_link ? { cityInstance: {root:o.city_link.root,id:o.city_link.instance,kind:o.city_link.kind,sourceClip:o.city_link.source_clip} } : {}),
    ...(o.city ? { city: {package:o.city.package} } : {}),
    ...(o.extents_mm ? { extents_mm: [...o.extents_mm] } : {}),
  }));
  if (!selected.length) return null;
  const cursor = mode === 'motion' && Number.isFinite(motion?.time_seconds) && motion.time_seconds >= 0
    ? { time_seconds: Number(motion.time_seconds.toFixed(3)),
      unsaved_preview: Boolean(motion.unsaved_preview), playing: Boolean(motion.playing) } : null;
  let label = t('selectionContext.label', {
    count: selected.length,
    names: selected.map(o => String(o.name).replace(/\s+/g, ' ').trim()).join(t('common.listSeparator')),
  });
  if (cursor) label = t('selectionContext.motionLabel', { label, time: cursor.time_seconds.toFixed(2) });
  const composerLabel = [...label].length > 72 ? [...label].slice(0, 71).join('') + '…' : label;
  const modeLabel = t(mode === 'motion' ? 'selectionContext.mode.motion' : editing ? 'selectionContext.mode.edit' : 'selectionContext.mode.print');
  return {
    content: [{ type: 'text', text: t('selectionContext.attachmentText', {
      modeLabel, names: selected.map(o => JSON.stringify(o.name)).join(t('common.listSeparator')),
    }) + (cursor ? '\n' + t('selectionContext.motionText', {
      time: cursor.time_seconds, dirty: String(cursor.unsaved_preview),
    }) : '') }],
    structuredContent: {
      source: editing ? '3D Workbench selection' : 'Print Prep selection',
      ...(state.workspace_id ? { workspace_id: state.workspace_id } : {}),
      job: state.job, revision: editing ? source.revision : state.rev, units: 'mm',
      ...(cursor ? { motion: cursor } : {}),
      ...(editing ? { selectedObjects: selected } : { selectedParts: selected }),
    },
    // Codex's ui/update-model-context extension (local host schema). Other hosts
    // still receive standard content + structuredContent without relying on it.
    presentation: { composerLabel },
  };
}

export function createSelectionContextSync(app) {
  let latest = null, desired = null, desiredKey = '', sentKey = null, running = null, disposed = false;
  async function drain() {
    while (desiredKey !== sentKey) {
      const next = desired, key = desiredKey;
      try {
        // An empty structuredContent object still creates a Codex attachment.
        // Empty content with no structuredContent removes the previous one.
        await app.updateModelContext(next || { content: [] });
        sentKey = key;
      } catch {
        // Delivery may be uncertain. Retry on a later refresh, or send the newer
        // pending clear now. The backend selection remains authoritative.
        sentKey = null;
        if (key === desiredKey) break;
      }
    }
  }
  function queue(next) {
    desired = next;
    desiredKey = desired ? JSON.stringify(desired) : '';
    if (!running && desiredKey !== sentKey) running = drain().finally(() => { running = null; });
    return running || Promise.resolve();
  }
  return {
    update({ mode, state, motion }) {
      if (disposed) return Promise.resolve();
      latest = selectionContext(mode, state, motion);
      // Restored/imported selection is editor state, not an attachment request.
      // Never restore a dismissed card on a poll or from another panel instance.
      // Invalidate a snapshot when its selection, mode or model version changes.
      return queue(desired && JSON.stringify(latest) === desiredKey ? desired : null);
    },
    attach() {
      if (disposed || !latest) return Promise.resolve();
      sentKey = null; // A new explicit click may reattach a manually dismissed card.
      return queue(latest);
    },
    clear() {
      if (disposed) return Promise.resolve();
      sentKey = null; // Also remove a context retained by the host across a reload.
      return queue(null);
    },
    dispose() {
      disposed = true; latest = null;
      // Serialize after any in-flight attachment so it cannot return after close.
      return queue(null);
    },
  };
}
