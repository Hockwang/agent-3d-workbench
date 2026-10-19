// Presentation only: model data remains in the validated backend workspace.
export const viewModes = ['home','edit','motion','print','tasks','observe','manufacture','laser'];
export function captureCamera(viewport) {
  const camera=viewport?.camera, controls=viewport?.orbit || viewport?.controls;
  return camera && controls ? {position:camera.position.toArray(),up:camera.up.toArray(),
    target:controls.target.toArray(),near:camera.near,far:camera.far,zoom:camera.zoom} : null;
}
export function restoreCamera(viewport, value) {
  const vector=v=>Array.isArray(v)&&v.length===3&&v.every(x=>Number.isFinite(x)&&Math.abs(x)<1e9);
  if(!value || !vector(value.position)||!vector(value.target)||!vector(value.up)
    ||!Number.isFinite(value.near)||!Number.isFinite(value.far)||value.near<=0||value.far<=value.near
    ||!Number.isFinite(value.zoom)||value.zoom<=0||value.zoom>1e5)return false;
  const camera=viewport?.camera, controls=viewport?.orbit || viewport?.controls;
  if(!camera||!controls)return false;
  camera.position.fromArray(value.position);camera.up.fromArray(value.up);
  camera.near=value.near;camera.far=value.far;camera.zoom=value.zoom;camera.updateProjectionMatrix();
  controls.target.fromArray(value.target);controls.update();viewport.userMoved=true;
  (viewport.loop||viewport._loop)?.invalidate();return true;
}
