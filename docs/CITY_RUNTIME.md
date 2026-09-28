# Full-city workbench (v0.8.3)

> 中文：[zh-CN/CITY_RUNTIME.md](zh-CN/CITY_RUNTIME.md)

The user has confirmed the [full-city integration plan](history/CITY_RUNTIME_PROPOSAL.md). Supports
the fixed source-code contract of the `cubely_lab_20260920.zip` attachment, fully importing terrain,
roads, buildings, characters, facilities, and the package's built-in behavior.
No extra GPT API call is needed; online NPC motion generation is turned off. The asset is provided
locally by the user and is not submitted or distributed with the plugin.

## Usage

1. In a standalone project/workbench, go to "Model Edit → Models & Objects → Full City," enter the
   Cubely ZIP's absolute path, and import it.
   The AI uses `studio_edit(action="city_import", params={path:...}, expected_revision=...)`.
2. The city opens automatically in the same viewport, paused by default. Search the list for a
   character/facility, or click an editable instance in the scene; the first selection loads the
   full GLB on demand.
   The AI uses `city_catalog(query,offset,limit)` to look up an instance, then
   `city_checkout(instance_id)`.
3. Existing move/rotate/scale, materials, and full-scene export/backfill continue to work. The
   workbench is still mm, Z-up; the inside of the city is m, Y-up.
   The selection context includes the edited object ID, the city instance ID, the asset version,
   and the motion binding.
4. "Run City" resumes the simulation; click into the viewport, then WASD to move, E for the car
   door, F to interact/get in or out, C to switch view.
   Editing continues after pausing. The position while running is a temporary preview; what's
   persisted is the edited layout, the source asset, and the modified version.
5. `scene_export` → the current GPT operates on local Blender → `scene_replace` to backfill in
   place.
   Preserves the character's original bone-name mapping and full source motion. The attachment's
   characters use 30 fps; Blender's default 24 fps export may truncate the last frame.
   An incompatible skeleton, a missing motion, or a truncated timeline is rejected, and the old
   object is left unchanged.
6. Motion mode turns off the city preview, inspecting the full character's/facility's skeleton and
   clips in the same renderer; going back to Model Edit and clicking "Open City" restores the whole
   city.
7. Saving the project outputs a self-contained `.3dworkbench`, including the frozen city package,
   the instance manifest, and local model edits.
   Exporting a GLB/STL for print requires explicitly selecting an already-loaded object; the city's
   resource entry point cannot be treated as a full-city mesh export.

Same-project part chats continue to follow scope, leases, per-part versions, and undo; workspace
branches continue to use three-way merge.
If two branches each load and edit the same city instance, it will reject a duplicate binding and
require the conflict to be resolved.

## Technical boundaries

- Shares the Studio's Three.js, WebGLRenderer, and RenderLoop. Closing the city releases city
  resources without destroying the host renderer.
- The city runtime owns the near/far for the metric camera; when the host focuses a local
  character/facility it only adjusts position and target, without applying the millimeter mesh's
  clipping math, to avoid a far-plane depth conflict on the ground. See the
  [flicker fix record](history/CITY_FLICKER_FIX_20260923.md).
- The city environment keeps its original zoning, InstancedMesh, distance-based loading, and the
  16-visible/22-resident facility budget; the whole-city resource entry point occupies just one
  workbench object.
  The fine-editing object cap of 500 still applies; an already-edited source GLB adds to memory —
  this is not an unlimited-scale editor.
- Facilities swap model per instance without polluting the shared template; moving/reshaping one
  rebuilds an independent AABB collision envelope and spatial index, and syncs interaction points,
  stopping any stale path/hail request.
  The envelope is not exact concave-mesh collision. Changing the placement of an originally-patrolling
  facility stops that instance's original patrol, to avoid the old route pulling it back to the
  original position.
- NPCs move and stick to the ground using the original behavior system; they are not an arbitrary
  free-floating 3D object. A compatible skeleton can be backfilled; there is not yet an automatic
  migrator for swapping skeletons/new semantic mappings.
- City instance delete/duplicate, direct `motion_set`, road topology, and terrain reshaping are not
  yet supported; selecting and editing while the city is running requires pausing first.
- Saving the project does not save an in-progress drive's instantaneous speed, story/collectible
  progress, or cross-window lockstep simulation.
- The runtime package is about 480 MB, and the self-contained project is about 336 MB; first
  compile and load take time. The city package freezes the source code and asset hashes; a
  different-version ZIP with a different contract will error out explicitly.
- Import only extracts the source code, public assets, and Rapier JS/WASM; it does not execute the
  attachment's npm scripts or native binaries.
  Each read verifies the asset hash and binds to the current workbench; archive restoration
  verifies all assets. Dynamic scripts require a trust receipt generated at the time of an explicit
  local import.
  When switching machines, import the same version from the original ZIP into a fresh project
  first, before opening the corresponding archive's runtime module.
- The run preview uses in-memory storage and does not depend on the embedding host's
  localStorage/IndexedDB. Basic walking/running comes from the original package's built-in motion.

Actual verification, the performance environment, and limits are in the
[acceptance record](history/VALIDATION_20260923_CITY.md).
