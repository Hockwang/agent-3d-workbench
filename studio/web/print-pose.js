import * as THREE from 'three';
import { STLExporter } from 'three/addons/exporters/STLExporter.js';

// Freeze the displayed pose into independent geometry-only print copies.
// getVertexPosition includes both morph targets and skin deformation.
export function printPoseFiles(root) {
  const files = [], exporter = new STLExporter(), point = new THREE.Vector3();
  root.updateMatrixWorld(true);
  root.traverse(object => object.skeleton?.update());
  root.traverseVisible(object => {
    if (!object.isMesh || !object.geometry?.attributes.position) return;
    const source = object.geometry, count = source.index?.count || source.attributes.position.count;
    const positions = new Float32Array(count * 3), mirrored = object.matrixWorld.determinant() < 0;
    for (let i = 0; i < count; i++) {
      const corner = mirrored && i % 3 ? i + (i % 3 === 1 ? 1 : -1) : i;
      object.getVertexPosition(source.index ? source.index.getX(corner) : corner, point).applyMatrix4(object.matrixWorld);
      positions.set([point.x * 1000, -point.z * 1000, point.y * 1000], i * 3);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const mesh = new THREE.Mesh(geometry);
    const name = (object.name || 'part').replace(/[^\p{L}\p{N}_-]/gu, '_').slice(0, 80);
    files.push({ name: `${String(files.length + 1).padStart(2, '0')}-${name}.stl`, bytes: exporter.parse(mesh, { binary: true }) });
    geometry.dispose(); mesh.material.dispose();
  });
  return files;
}
