"""Replay creation -> scoped edit -> ZIP export -> clean reopen -> edit over real MCP.

uv run python examples/motion_editing/verify_tutorial.py --out /absolute/new/directory
Optional --source: a static metre/Y-up GLB with body/drawer_left/drawer_middle/drawer_right
nodes (material primitive suffixes are supported and moved together).
This is a deterministic product tutorial, not a blind model comparison.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client
import studio
from studio.core.editor import _glb_document


def make_source(path):
    scene = trimesh.Scene()
    def box(size, position, color):
        mesh = trimesh.creation.box(size)
        mesh.apply_translation(position)
        mesh.visual.vertex_colors = color
        return mesh
    body = [box([1.8, .06, .7], [0, .75, 0], [178, 150, 113, 255])]
    for x in [-.85, .85]:
        for z in [-.29, .29]:
            body.append(box([.07, .72, .07], [x, .36, z], [60, 65, 78, 255]))
    scene.add_geometry(trimesh.util.concatenate(body), node_name='body', geom_name='body')
    for name, x in [('drawer_left', -.58), ('drawer_middle', 0), ('drawer_right', .58)]:
        mesh = trimesh.util.concatenate([
            box([.52, .03, .52], [x, .61, 0], [90, 134, 188, 255]),
            box([.54, .12, .03], [x, .655, -.275], [75, 116, 168, 255]),
            box([.14, .025, .035], [x, .65, -.3], [203, 210, 216, 255]),
        ])
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    path.write_bytes(scene.export(file_type='glb'))


def motion(delay):
    return dict(schema='studio-motion/v1', kind='joint', duration=8, fps=24, mode='pkf',
                joint=dict(type='prismatic', axis='y', origin=[0, 0, 0], parent=None, limits=[-.28, 0]),
                parameters=[dict(id='travel', default=.28, unit='m')], keyframes=[], steps=[
                    dict(id='open', t_start=delay, t_end=delay+2, value_start='0', value_end='-travel', easing='linear'),
                    dict(id='hold', t_start=delay+2, t_end=delay+2.5, value_start='-travel', value_end='-travel', easing='linear'),
                    dict(id='close', t_start=delay+2.5, t_end=delay+4.5, value_start='-travel', value_end='0', easing='linear')])


def part_name(name):
    return next((part for part in ['body','drawer_left','drawer_middle','drawer_right']
                 if name == part or name.startswith(part+'_')), None)


async def verify(out, source):
    if source is None:
        source = out / 'input.glb'
        make_source(source)
    calls, stages = [], {}
    # No configured external generation service or user project is attached to either server.
    config = out / 'services.json'
    config.write_text('{"providers":{}}\n')
    for phase in ['create', 'reopen']:
        home = out / phase
        env = {'PRINT_PREP_HOME':str(home), 'PRINT_PREP_WORKSPACES_HOME':str(home),
               'PRINT_PREP_WORKSPACE_ID':'motion-tutorial', 'CODEX_HOME':str(out/'empty-codex'),
               'WORKBENCH_SERVICE_CONFIG':str(config), 'STUDIO_LANG':'en'}
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT/'studio/shell/mcp_server.py')], env=env)
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    async def call(name, args=None):
                        result = await client.call_tool(name, args or {})
                        if result.is_error:
                            raise RuntimeError(f'{name}: {result.content}')
                        calls.append(name)
                        return result.structured_content or json.loads(result.content[0].text)
                    async def state():
                        return (await call('studio_get_state'))['workbench']
                    async def edit(action, data=None):
                        s = await state()
                        return await call('studio_edit', dict(action=action, expected_revision=s['revision'], params=data or {}))
                    async def set_motion(name, value):
                        s = await state()
                        obj = next(o for o in s['objects'] if o['name'] == name)
                        return await call('studio_motion', dict(action='set', expected_revision=s['revision'],
                            **({'expected_versions':{obj['id']:obj['version']}} if 'version' in obj else {}),
                            params={'ids':[obj['id']], 'motion':value}))
                    async def export(label):
                        result = {}
                        for fmt in ['zip', 'glb']:
                            s = await state()
                            result[fmt] = (await call('studio_motion', dict(action='export', expected_revision=s['revision'],
                                params={'format':fmt, 'path':str(out/f'{label}.{fmt}')})))['path']
                        stages[label] = {'objects':s['objects'], **result}
                        doc = _glb_document(Path(result['glb']).read_bytes())
                        assert doc.get('animations') and doc.get('meshes')
                    await call('studio_open', {'mode':'motion'})
                    if phase == 'create':
                        await edit('import', {'files':[str(source)]})
                        original = (await state())['objects']
                        assert {part_name(o['name']) for o in original} == {'body','drawer_left','drawer_middle','drawer_right'}
                        for obj in original:
                            part = part_name(obj['name'])
                            if part != 'body':
                                delay = ['drawer_left','drawer_middle','drawer_right'].index(part)*.5
                                await set_motion(obj['name'], motion(delay))
                        await export('01-open-in-order')
                        before = {o['name']:o for o in (await state())['objects']}
                        for name, obj in before.items():
                            if part_name(name) == 'drawer_middle':
                                modified = copy.deepcopy(obj['motion'])
                                modified['steps'][1]['t_end'] += 2
                                modified['steps'][2]['t_start'] += 2
                                modified['steps'][2]['t_end'] += 2
                                await set_motion(name, modified)
                        after = {o['name']:o for o in (await state())['objects']}
                        for name in before:
                            if part_name(name) != 'drawer_middle':
                                assert after[name] == before[name], name
                        assert all(after[o['name']]['asset'] == o['asset'] for o in original)
                        await export('02-middle-hold')
                        await edit('save', {'path':str(out/'editable.3dworkbench')})
                    else:
                        await edit('motion_import', {'path':stages['02-middle-hold']['zip']})
                        current = {o['name']:o for o in (await state())['objects']}
                        expected = {o['name']:o for o in stages['02-middle-hold']['objects']}
                        for name in current:
                            assert current[name]['asset'] == expected[name]['asset']
                            if part_name(name) != 'body':
                                assert current[name]['motion']['steps'] == expected[name]['motion']['steps']
                        for name, obj in current.items():
                            if part_name(name) == 'drawer_middle':
                                modified = copy.deepcopy(obj['motion'])
                                modified['parameters'][0]['default'] = .18
                                await set_motion(name, modified)
                        await export('03-reopened-shorter-travel')
        finally:
            studio.stop_server(home=home)
            for folder in (home/'workspaces').glob('*'):
                studio.stop_server(home=folder)
    (out/'stages.json').write_text(json.dumps(stages, indent=2)+'\n')
    # Check sampled world translations against the prescribed motion, not just file existence.
    probe = out/'check.mjs'
    probe.write_text('''import fs from 'node:fs';
import {MechanicalMotion} from '''+json.dumps((ROOT/'studio/web/motion-engine.js').as_uri())+''';
const stages=JSON.parse(fs.readFileSync(process.argv[2]));
let samples=0;
for(const [label,s] of Object.entries(stages)) {
 const runtime=new MechanicalMotion(s.objects);
 for(let frame=0;frame<=192;frame++) {
  const time=frame/24;runtime.seek(time);
  for(const o of s.objects) {
   let travel=0;
   const part=['body','drawer_left','drawer_middle','drawer_right'].find(n=>o.name===n||o.name.startsWith(n+'_'));
   if(part!=='body') {
    const delay={drawer_left:0,drawer_middle:.5,drawer_right:1}[part];
    const hold=part==='drawer_middle'&&label!=='01-open-in-order'?2:0;
    const range=part==='drawer_middle'&&label==='03-reopened-shorter-travel'?.18:.28;
    const close=delay+2.5+hold;
    travel=time<delay?0:time<delay+2?range*(time-delay)/2:time<=close?range:Math.max(0,range*(1-(time-close)/2));
   }
   const m=runtime.studioMatrix(o).elements;
   for(let axis=0;axis<3;axis++) {
    const expected=o.transform[axis][3]+(axis===1?travel*1000:0);
    if(Math.abs(m[12+axis]-expected)>1e-5)throw Error(`${label} ${o.name} ${time} axis ${axis}: ${m[12+axis]} != ${expected}`);
   }
   samples++;
  }
 }
}
console.log(JSON.stringify({world_translation_samples:samples,passed:true}));
''')
    checks = json.loads(subprocess.check_output(['node', str(probe), str(out/'stages.json')], text=True))
    return {'status':'pass', 'source':str(source), 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'source_kind':'provided static four-part GLB' if source != out/'input.glb' else 'procedural tutorial fixture',
            'stages':{k:{fmt:v[fmt] for fmt in ['zip','glb']} for k,v in stages.items()},
            'checks':checks, 'unselected_objects_unchanged':True, 'fresh_reopen_editable':True,
            'external_apis':False, 'blind_model_comparison':False, 'mcp_calls':calls,
            'limitations':['Kinematic tutorial; no new collision, physical scale or naturalness validation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    out = args.out.expanduser().resolve() if args.out else Path(tempfile.mkdtemp(prefix='motion-tutorial-'))
    if args.out:
        out.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(verify(out, args.source.expanduser().resolve() if args.source else None))
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'report':str(out/'report.json'), 'status':report['status'], 'checks':report['checks']}))


if __name__ == '__main__':
    main()
