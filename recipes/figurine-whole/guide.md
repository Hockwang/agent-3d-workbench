# 整件手办直接打

## 什么时候用
- 一个不需要拆件的手办、雕塑或人物摆件，要整体打印。
- 模型本身立得住，想保持原始站姿（不想被自动策略摆平打印）。
- 细长直立，容易在打印中途被喷头蹭倒或震歪，需要外圈 brim 帮忙站稳。

## 什么时候别用
- 打算拆成能分开打印、再胶装回去的件——改用 `split-glue-kit`。
- 背面平、正面是浮雕/文字的薄板——改用 `relief-plate`，那条路线贴床摆放、不加支撑。
- 带承力孔、需要壁厚/填充加强的结构功能件——改用 `functional-part`。
- 肢段已经分好、想让它能摆姿势——改用 `poseable-figure`。

## 路线与判断点

### model · studio_load
先看返回里的 `watertight`、`fits_bed`、`extents_mm` 和顶层 `warnings`。放不下时看 `suggested_scale`，问清楚要不要用 `target_max_mm` 统一缩放（缩的是全体零件合在一起的包围盒），不要自己按经验乘除。最长边小于 5 mm 或大于 2000 mm 多半是源文件单位不对。过的标准：`readiness` 里 `model` 为 `pass`。

### orient · studio_orient
`shape: figurine` 会先尝试保持原始朝向（`upright` 策略）；如果源文件里模型本来的姿势站不稳，会自动退让成 `support`（悬空最少的姿势）。这一步要看：`warnings` 里有没有 `unstable_contact`（最终朝向贴床面积小于 20 mm²，很多手办的脚尖、裙摆、单腿站姿会踩这条线）；`upright_rejected` 是不是 `true`，为真时 `upright_rejected_reason` 里带着具体的贴床面积数字。出现 `unstable_contact` 时，要么接受（配合树状支撑和 brim 站住，如实告诉用户这件靠支撑撑着），要么从 `top_candidates` 里挑一个贴床面积更大的候选，要么用 `set` 手工指定 `print_up`。`upright_rejected: true` 不是失败，是自动帮它换了更稳的姿势，把原因转述给用户。过的标准：没有还没处理的 `unstable_contact`。

### arrange · studio_arrange
`mode: auto`：单盘放不下自动开新盘。过的标准：`readiness` 里 `arrange` 为 `pass`。`single_plate_overflow` 报错会带 `needed_plates_with_auto`；单件放不下会给 `suggested_scale`。

### export · studio_export
逐盘检查 `unmatched_parts`（应为空）和 `bambu_moved_objects`（应为 `false`）。任一异常都要如实告诉用户对不上，不要说"完全按计划摆好了"。过的标准：`readiness` 里 `export` 为 `pass`。

### check · studio_check
**没跑这一步就不要报克数和时长**，直接说还没估算。看每盘的 `grams`、`seconds`、`warnings`；有 warnings 就转述原文，不要总结成"没问题"。

### deliver · studio_send_to_bambu
多盘默认只打开第 1 盘，其余盘的 `project_3mf` 路径完整列给用户；用户明确要求才传 `all: true`。`was_running_before` 为真提醒用户 Bambu Studio 原本就开着，可能先弹窗问要不要保存当前工程。`loaded` 恒为 `unverified`，只能说"已请求打开"，不能说"已加载完成"，也不能替用户点打印。

## 我们踩过的坑
- 手办、球形、尖底的件很常见贴床面积不够（低于 20 mm² 的稳定线），出现 `unstable_contact` 不是 bug，是真的会倒或印歪，需要支撑和 brim 兜底（print_prep/orient.py）。
- 树状支撑（`tree(auto)`）比普通支撑更省料也更容易剥离，支撑能从半空里长出来接住悬空的手臂/发梢；外圈 brim（`outer_only`，3 mm）专门用来防细长直立件在打印中途被蹭倒——这两个不是随手选的默认值，是手办这一类形状总结出来的经验档位（print_prep/shape_table.py）。
- 整件不拆件打印，"跑完没报错"不等于"没有偷偷改动模型"：至少确认过 STL/3MF 往返之后仍然水密、三角形数没变、顶点误差在数值零的量级，才敢说这一步的准备工作是干净的（fdm_preprint/RESULTS.md，001 机器人案）。

## 收口时告诉用户
- 载入了几件、有没有不水密/放不下的告警。
- 最终朝向是不是原始站姿；有没有因为不稳被自动改成别的朝向，原因是什么；是不是手工指定的。
- 分了几盘、工艺预设（figurine 档：0.16 mm 层高、树状支撑、外圈 brim）与耗材预设。
- 有没有试切：跑了就报克数和时长，没跑就说没估算。
- 请求 Bambu Studio 打开了哪个工程文件，其余盘的文件路径给全。

## 出处
- print_prep/shape_table.py（2026-09-19）
- print_prep/orient.py（2026-09-19）
- fdm_preprint/RESULTS.md（2026-09-08）
