# 多件套件分盘

## 什么时候用
- 已经有一整套拆好的零件（多个网格文件，或一个把多个节点打包在一起的文件），要作为同一次交付一起打印。
- 套件里有朝向很重要的零件——比如一张脸、一块正面板——自动策略选出来的贴床面或支撑面有可能正好是这一面。
- 件数比较多，想按盘走一遍，看清会分几盘、每盘多重、打多久，再决定要不要发去打印机界面。

## 什么时候别用
- 只有一件、朝向没有争议：直接调 `studio_load`/`studio_orient`，或者用 `estimate-only`，不用整条路线。
- 零件之间要靠插拔的孔轴、销钉、卡扣配合：先走 `test-coupon-first` 打一组试片，确认间隙再回来分这条路线。

## 路线与判断点

### model · studio_load
载入这一套全部文件。先看返回里逐件的 `watertight`、`fits_bed`、`components`、`extents_mm`；场景类文件（GLB/GLTF/3MF 的多节点）默认按节点各算一件，要合并成一件才传 `merge: true`。放不下时看 `suggested_scale`，问清楚要不要缩放，不要按经验自己乘除。过的标准：`readiness` 里 `model` 为 `pass`。

### orient · studio_orient
这一步是这条路线里必须停下来看一眼的地方。先按外形选一个 `shape`（`figurine`/`relief`/`mechanical`/`generic`），跑一次默认策略；再逐件看 `warnings` 里有没有 `unstable_contact`（贴床面积不到 20 mm²）和 `top_candidates`。光看 `warnings` 不够——它只报"稳不稳"，不知道哪一面是外观正面。哪一件的哪一面不能拿去贴床或扛支撑，需要认出来，认出来之后用 `set: {零件名: [x,y,z]}` 手工指定，不要指望 `strategy` 自动避开。过的标准：没有还没处理的 `unstable_contact`，且外观关键面确认没有落在支撑侧。

### arrange · studio_arrange
`mode: auto`：单盘放不下就自动开新盘，不用先猜零件能不能挤进一盘。件数多、外观件比较精细时可以把 `gap` 调大一点，给后面清理支撑留空间。过的标准：`readiness` 里 `arrange` 为 `pass`，`plates` 数字拿到手。

### export · studio_export
`shape` 缺省沿用 orient 定下来的那个。逐盘检查 `unmatched_parts` 和 `used_slice_fallback`：任一个非空/为真都要如实告诉用户，不能说"完全按计划摆好了"。过的标准：`readiness` 里 `export` 为 `pass`。

### check · studio_check
默认全部盘都试切一遍。没跑这一步就不要报克数和时长，直接说还没估算。任一盘 `returncode != 0` 或 `warnings` 非空都要照原文转述，不要总结成"没问题"。过的标准：每盘 `returncode` 为 0 且 `warnings` 为空数组。

### deliver · studio_send_to_bambu
默认只发第 1 盘（`plate` 缺省即第 1 盘），其余几盘的 `project_3mf` 路径要完整列给用户，不要因为已经开了一盘就不提。用户明确要求才传 `all: true`；这条路线不预设它。发送之后 `loaded` 恒为 `unverified`，只能说"已请求打开"，不能说"已经载入"。

## 我们踩过的坑
- 六件套件胶装时，件间距是从实测装配路径里量出来的（0.25 mm 的局部避让带），不是随便定的；分盘之间的间距如果留白不够，逐盘核验时才会发现装不进去（fdm_preprint/assembly_connectors_028）。
- 十件以上的套件如果一件一盘去核验朝向，能把"这件到底该哪面朝上"的问题在正式分盘前解决掉，比分完盘再挑一件重来省事（fdm_preprint/rig_print_023）。
- "近距支撑为 0"只对专门定义的那张脸/那块正面成立，其余区域（比如脑后、底座背面）通常还有几千段支撑，不能因为正面测出 0 就说"整张脸无支撑"（fdm_preprint/static_kit_015）。
- 关节/配合孔的方向选对了（横放而不是竖着穿），孔内支撑能从有变没有；但两耳之间的开放槽即使孔本身干净，仍然会被判成需要清理的支撑，不能因为孔干净了就当整个接口都不用清理（fdm_preprint/articulated_029）。

## 收口时告诉用户
- 几件、分了几盘；哪几件带过 `unstable_contact` 或非水密之类的告警，最后是自动策略还是手工 `set` 定的朝向。
- 每盘 `unmatched_parts`/`used_slice_fallback` 是否为空/为假；不是就如实说。
- 有没有跑 `check`：跑了就报每盘克数和时长，没跑就说还没估算。
- 请求打开了哪一盘的工程文件；其余盘的 `project_3mf` 路径完整列出来，不自动打开。

## 出处
- fdm_preprint/assembly_connectors_028（2026-09-16）
- fdm_preprint/rig_print_023（2026-09-16）
- fdm_preprint/static_kit_015（2026-09-15）
- fdm_preprint/articulated_029（2026-09-16）
