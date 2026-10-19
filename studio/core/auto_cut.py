"""Bounded geometric cut-to-fit planning on an isolated print copy.

No LLM or semantic face/connector recognition is implied. The agent/UI can call
this deterministic tool: try orientations, compare capped plane cuts, verify,
arrange and export. Publish a new job only when the entire transaction succeeds.
"""
from __future__ import annotations

import itertools
import json
import math
import shutil
import tempfile
from pathlib import Path

import manifold3d
import numpy as np
import trimesh

from print_prep import arrange, cli, job, mesh_io, orient, printer_catalog, profiles
from studio.i18n import render


def fail(key, **params):
    raise cli.UserError(render(f'auto_cut.{key}', **params), code=f'auto_cut_{key}')


class CutPlanner:
    def __init__(self, bed, *, max_pieces=32, max_cuts=288, progress=None):
        self.bed = bed
        self.max_pieces = max_pieces
        self.max_cuts = max_cuts
        self.attempts = 0
        self.progress = progress or (lambda text: None)
        self.capacity = np.asarray(bed['bed_mm']) - np.array([2, 2, 1]) * bed['margin_mm']

    def fitting_orientation(self, mesh, preferred=None, *, require_stable=False):
        # Convex hull has exactly the same bounding box under any rotation.
        # Only fit candidates are evaluated against the full surface afterwards.
        hull = mesh.convex_hull
        candidates = [] if preferred is None else [orient.unit(preferred)]
        candidates.extend(sign * axis for axis in np.eye(3) for sign in (1, -1))
        candidates.extend(-normal for normal, _ in orient.planar_patch_normals(mesh)[:12])
        candidates.extend(orient.fibonacci_sphere(32))
        fits, forced = [], []
        seen = set()
        for index, up in enumerate(candidates):
            key = tuple(np.round(up, 6))
            if key in seen:
                continue
            seen.add(key)
            try:
                arrange.arrange([{'name': 'probe', 'mesh': hull, 'print_up': up}], **self.bed)
            except arrange.PartTooLargeError:
                continue
            if preferred is not None and np.allclose(up, orient.unit(preferred)):
                if not require_stable or orient.base_contact_area(mesh, up) >= orient.STABLE_CONTACT_MM2:
                    return np.asarray(up)
            fits.append(up)
            forced.append(index < len(candidates) - 32)
        if not fits:
            return None
        ranked = orient.rank_candidates(mesh, fits, forced=forced, top_k=6)
        if require_stable:
            ranked = [m for m in ranked if m['contact_area_mm2'] >= orient.STABLE_CONTACT_MM2]
            if not ranked:
                return None
        best = min(ranked, key=lambda m: (m['contact_area_mm2'] < orient.STABLE_CONTACT_MM2,
                                        m['overhang_area_mm2'], -m['contact_area_mm2'], m['height_mm']))
        return np.asarray(best['print_up'])

    def estimate_pieces(self, mesh):
        # A ranking heuristic, not a proof of fit. Every chosen leaf must pass
        # the actual packer, including the machine's exclusion zones.
        return min(math.prod(np.maximum(1, np.ceil(np.asarray(dims) / self.capacity)).astype(int))
                   for dims in itertools.permutations(mesh.extents))

    def split(self, mesh, axis, fraction):
        if self.attempts >= self.max_cuts:
            fail('limit', limit=self.max_cuts)
        self.attempts += 1
        solid = manifold3d.Manifold(manifold3d.Mesh64(
            np.array(mesh.vertices, dtype=np.float64, order='C', copy=True),
            np.array(mesh.faces, dtype=np.uint64, order='C', copy=True)))
        if solid.status() != manifold3d.Error.NoError:
            fail('closed')
        normal = np.eye(3)[axis]
        offset = float(mesh.bounds[0, axis] + mesh.extents[axis] * fraction)
        outputs = []
        for half in solid.split_by_plane(normal, offset):
            if half.is_empty() or half.status() != manifold3d.Error.NoError:
                return None
            data = half.to_mesh64()
            piece = trimesh.Trimesh(np.asarray(data.vert_properties)[:, :3], data.tri_verts, process=False)
            if not piece.is_volume or piece.volume < max(mesh.volume * .01, .01):
                return None
            outputs.append(piece)
        if not np.isclose(sum(p.volume for p in outputs), mesh.volume, rtol=1e-5, atol=1e-6):
            return None
        area = max(0., (sum(p.area for p in outputs) - mesh.area) / 2)
        return outputs, {'axis': 'XYZ'[axis], 'offset_mm': offset, 'area_mm2': float(area)}

    def plan(self, mesh, name, preferred=None):
        cuts = []
        pieces = []
        pending = [(mesh, preferred, 0)]
        while pending:
            current, up, depth = pending.pop(0)
            self.progress(render('auto_cut.searching', name=name, count=len(pieces) + len(pending) + 1))
            chosen = self.fitting_orientation(current, up, require_stable=depth > 0)
            if chosen is not None:
                pieces.append({'mesh': current, 'print_up': chosen.tolist()})
                continue
            if not current.is_volume:
                fail('closed')
            if depth >= 8 or len(pieces) + len(pending) + 2 > self.max_pieces:
                fail('limit', limit=self.max_pieces)
            candidates = []
            for axis in np.argsort(-current.extents):
                for fraction in (.5, .4, .6):
                    split = self.split(current, axis, fraction)
                    if split is None:
                        continue
                    children, detail = split
                    child_ups = [self.fitting_orientation(p, require_stable=True) for p in children]
                    cost = sum(1 if v is not None else max(2, self.estimate_pieces(p))
                               for p, v in zip(children, child_ups))
                    # Prefer fewer estimated pieces, then smaller seams and
                    # balanced volumes. Search is bounded; no optimality claim.
                    score = (cost, detail['area_mm2'], abs(children[0].volume - children[1].volume))
                    candidates.append((score, children, child_ups, detail))
            if not candidates:
                fail('no_plan', name=name)
            _, children, child_ups, detail = min(candidates, key=lambda c: c[0])
            cuts.append({**detail, 'depth': depth, 'candidates_compared': len(candidates)})
            pending.extend((p, v, depth + 1) for p, v in zip(children, child_ups))
        bounds = np.asarray([p['mesh'].bounds for p in pieces])
        volume = sum(p['mesh'].volume for p in pieces)
        if cuts and (not np.isclose(volume, mesh.volume, rtol=1e-5, atol=1e-6)
                     or not np.allclose([bounds[:, 0].min(0), bounds[:, 1].max(0)], mesh.bounds, atol=1e-5)):
            fail('verification')
        return {'pieces': pieces, 'cuts': cuts, 'source_volume_mm3': float(mesh.volume),
                'result_volume_mm3': float(volume)}


def prepare_copy(job_dir: Path, body, *, progress=None):
    from studio.core import print_state

    progress = progress or (lambda text: None)
    before = job.load_job(job_dir)
    source = before.get('inspect', {})
    if not source.get('parts'):
        fail('missing')
    # Auto recovery operates on the already loaded, already scaled print copy.
    # Mixing a new upload/size/printer into this transaction is ambiguous.
    if any(k in body for k in ('files', 'scale', 'target_max_mm', 'merge', 'printer')) or body.get('send'):
        fail('arguments')
    gap = print_state.to_float(body.get('gap', cli.DEFAULT_GAP_MM), 'gap')
    if not np.isfinite(gap) or gap < 0:
        fail('arguments')
    if len(source['parts']) > 128:
        fail('limit', limit=128)
    _, _, idx, native_name = printer_catalog.context(source['printer'])
    bed = {**profiles.bed_params(profiles.resolve(native_name, idx)), 'margin_mm': cli.DEFAULT_MARGIN_MM}
    hashes = {p['stl_path']: job.sha256_file(Path(p['stl_path'])) for p in source['parts']}
    root = job_dir / 'print-inputs'
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='auto-cut-', dir=root))
    try:
        files, directions, details = [], {}, []
        used_names = {p['name'] for p in source['parts']}
        for meta in source['parts']:
            mesh = mesh_io.load_part_stl(meta['stl_path'])
            preferred = (before.get('orient', {}).get('parts', {}).get(meta['name']) or {}).get('print_up')
            try:
                plan = CutPlanner(bed, progress=progress).plan(mesh, meta['name'], preferred)
            except cli.UserError as exc:
                exc.payload = {**(exc.payload or {}), 'part': meta['name']}
                raise
            names = []
            for i, piece in enumerate(plan['pieces'], 1):
                name = meta['name'] if not plan['cuts'] else f"{meta['name']}_cut_{i}"
                while plan['cuts'] and name in used_names:
                    name += '_copy'
                used_names.add(name)
                path = stage / 'sources' / f'{name}.stl'
                if not plan['cuts']:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(meta['stl_path'], path)
                else:
                    mesh_io.save_part_stl(piece['mesh'], path)
                    saved = mesh_io.load_part_stl(path)
                    if not saved.is_volume or not np.isclose(saved.volume, piece['mesh'].volume, rtol=1e-5, atol=1e-5):
                        fail('verification')
                files.append(str(path))
                names.append(name)
                directions[name] = piece['print_up']
            details.append({'source': meta['name'], 'outputs': names, 'cuts': plan['cuts'],
                            'source_volume_mm3': plan['source_volume_mm3'],
                            'result_volume_mm3': plan['result_volume_mm3']})
            if len(files) > 128:
                fail('limit', limit=128)
        progress(render('auto_cut.arranging'))
        steps = []
        def record(step, result):
            steps.append({'step': step, 'result': result})
        record('inspect', print_state.api_load(stage, {'files': files, 'printer': source['printer']}))
        record('orient', print_state.api_orient(stage, {'shape': body.get('shape'), 'set': directions}))
        record('arrange', print_state.api_arrange(stage, {'mode': 'auto', 'gap': gap}))
        progress(render('auto_cut.exporting'))
        record('export', print_state.api_export(stage, {'shape': body.get('shape'), 'process': body.get('process'),
               'filament': body.get('filament'), 'set': body.get('export_set', {}),
               'no_project': body.get('no_project', False)}))
        if body.get('check'):
            progress(render('auto_cut.checking'))
            record('check', print_state.api_check(stage, {}))
        # Recheck original file bytes before publishing (external writers do not
        # participate in the Studio write lock). A failure leaves the old job.
        if job.load_job(job_dir) != before or any(job.sha256_file(Path(p)) != sha for p, sha in hashes.items()):
            fail('changed')
        staged = job.load_job(stage)
        report = {'planner': 'geometric-plane-search-v1', 'input_parts': len(source['parts']),
                  'output_parts': len(files), 'cut_count': sum(len(d['cuts']) for d in details),
                  'plates': len(staged['arrange']['plates']), 'original_size_preserved': True,
                  'connections_generated': False, 'semantic_protection': False,
                  'source_sha256': hashes, 'parts': details, 'report_path': str(stage / 'cut-report.json')}
        (stage / 'cut-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
        staged['inspect']['auto_cut'] = report
        job.save_job(job_dir, {**{k: v for k, v in before.items() if k not in job.STEP_ORDER}, **staged})
        return {'ok': True, 'print_submitted': False, 'steps': steps, 'auto_cut': report}
    except Exception:
        shutil.rmtree(stage)
        raise
