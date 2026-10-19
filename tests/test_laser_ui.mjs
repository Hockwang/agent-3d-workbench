import test from 'node:test';
import assert from 'node:assert/strict';
import {createLaser,laserStepCompleted} from '../studio/web/laser.js';

test('a partially imported project disables only sheets already imported',()=>{
  const partial={status:'partial',report:{imported_sheets:[2]}};
  assert.equal(laserStepCompleted(partial,'lightburn',2),true);
  assert.equal(laserStepCompleted(partial,'lightburn',1),false);
  assert.equal(laserStepCompleted({status:'completed'},'lightburn',1),true);
  assert.equal(laserStepCompleted(undefined,'design',1),false);
});

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.value='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(key,value){this.attributes[key]=value;}
  get options(){return this.children;}
}
function descendants(node){return [node,...node.children.flatMap(descendants)];}
test('laser polling preserves native menu options and in-progress parameter edits',async t=>{
  const root=new Element('main'),old=globalThis.document;
  globalThis.document={getElementById:()=>root,createElement:tag=>new Element(tag)};
  t.after(()=>{if(old===undefined)delete globalThis.document;else globalThis.document=old;});
  t.mock.method(globalThis,'setInterval',()=>0);t.mock.method(globalThis,'clearInterval',()=>{});
  const workflow={id:'a',title:'Original',revision:0,stages:{},params:{width_mm:230}};
  let rows=[workflow];
  const api={laser:async body=>body.action==='list'?{workflows:rows}:{workflow}};
  const laser=createLaser(api);t.after(()=>laser.dispose());await laser.ready;
  const all=descendants(root),picker=all.find(n=>n.tag==='select'),refresh=root.children[0].children.at(-1);
  const originalOption=picker.options[0],width=all.find(n=>n.name==='width_mm');
  width.value='310';
  await refresh.onclick();await refresh.onclick();
  assert.equal(picker.options[0],originalOption,'unchanged polling must not dismiss an open native menu');
  assert.equal(width.value,'310','polling must not overwrite a draft parameter');
  rows=[workflow,{...workflow,id:'b',title:'New'}];await refresh.onclick();
  assert.equal(picker.options.length,2,'actual workflow changes still update the menu');
  assert.equal(picker.value,'a','current selection remains selected');
});
