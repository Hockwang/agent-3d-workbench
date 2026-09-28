# 只估料和时间

## 什么时候用
- 要给一个方案，或几个候选，估算材料克数和打印时长，用来比较或者报价。
- 只想知道放不放得下床、会分几盘，还没决定真的要打印。
- 手上有几个候选朝向或工艺想比时间和耗材，最后只挑一个继续往下走。

## 什么时候别用
- 已经决定要打印、要把工程发到 Bambu Studio 图形界面：这条路线到 `check` 为止，交付另外单独调用工具。
- 套件里有需要人工核对的外观关键面：换 `kit-plates`，那条路线在 `orient` 这一步会明确停下来看一眼。

## 路线与判断点

### model · studio_load
载入要估算的文件。放不下时看 `suggested_scale`；最长边小于 5 mm 或大于 2000 mm 多半是单位错了，问清楚再继续，不要自己猜着换算。过的标准：`readiness` 里 `model` 为 `pass` 或只是 `warn`（比如不水密只报告，不强行修）。

### orient · studio_orient
按外形挑一个 `shape` 标签（`generic`/`figurine`/`relief`/`mechanical`），用 `strategy: auto` 让它按 shape 查表选策略。这一步是为了让后面的工艺档位和朝向有个合理起点，不追求跟 `kit-plates` 一样逐件停下来人工核对——但 `warnings` 里出现的 `unstable_contact` 还是要如实带进估算说明，不要吞掉。

### arrange · studio_arrange
`mode: auto`。这一步的 `plates` 数字决定了后面要跑几次导出和试切，多盘意味着克数和时长要按盘分别报再相加，不能只报一盘当总数。

### export · studio_export
`shape` 沿用 orient 那一步定的。逐盘看 `unmatched_parts`——非空的话，这一盘的估算数字仍然有效，但要在估算说明里带一句"有零件没对齐上"，不要藏起来。

### check · studio_check
默认全部盘都试切。这是这条路线唯一会产生"能不能报数字"的开关：没跑到这一步的盘不能报克数和时长，只能说"还没估算"；`returncode != 0` 的盘不计入合计，单独说明失败了。

## 我们踩过的坑
- 克数和时长只能来自 `check` 的返回，不能凭经验估；哪怕件数和体积都已经知道，没跑试切就是没有数字（fdm_preprint/rig_print_023 的逐案报法）。
- 多件同时排在一张床上时，耗材和时间不能只看整盘合计——要先按盘拆开各自的克数和时长再相加成总数，否则比较不同方案时会把"盘数不同"的差异吃掉（fdm_preprint/mechanical_joints_035）。
- 单独的试片（用来估算或验证参数）值得算成独立的一盘、独立报数字，不要并进正式套件的合计里，两者用途不一样（fdm_preprint/joint_library_032）。

## 收口时告诉用户
- 估的是哪个方案/哪一批文件，件数、分了几盘。
- 每盘的克数和时长，以及合计；`returncode` 非 0 的盘单独说明，不计入合计。
- 有没有 `unmatched_parts`、`unstable_contact` 之类的告警，即使不影响估算数字也要提一句。
- 明确这只是估算，不含支撑清理、后处理、组装等人工耗时，也没有发送到 Bambu Studio。

## 出处
- fdm_preprint/rig_print_023（2026-09-16）
- fdm_preprint/joint_library_032（2026-09-17）
- fdm_preprint/mechanical_joints_035（2026-09-17）
