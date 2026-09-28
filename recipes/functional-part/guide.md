# 功能件与结构件

## 什么时候用
- 支架、外壳、卡扣等结构件或功能件，需要够强度而不只是好看。
- 带装配用的孔、槽或轴，孔的方向会影响装配后的受力路径。
- 想要偏结构强度的工艺档位（4 层壁、20% 填充）而不是外观细节档位。

## 什么时候别用
- 纯外观的手办/雕塑——改用 `figurine-whole`。
- 浮雕/铭牌类薄板——改用 `relief-plate`。
- 件里有明确的铰链、滑轨、回转支承这类机构——改用 `mechanical-joints`。
- 这套配合公差没在这台机器、这个耗材上验证过——先用 `test-coupon-first` 打试片。

## 路线与判断点

### model · studio_load
要定什么：尺寸单位对不对。结构件通常有精确的配合公差，单位错了配合尺寸会全错，最长边异常先问用户实际尺寸，别自己乘除猜。过的标准：`readiness` 里 `model` 为 `pass`。

### orient · studio_orient
这一步工具本身给不出答案，需要人对装配场景的了解：这个件装到实际结构里之后，真正的受力方向是哪个；哪几个孔是承力/装配用的孔。`shape: mechanical` 会自动选 `flat`（贴床面积最大、悬空最小），但算法不知道你的装配场景，选出来的朝向可能让承力孔的轴线朝上（竖着），支撑很容易顺着孔壁长进去。看 `print_up`、`top_candidates`、`warnings`——这几个字段只告诉你"哪个朝向最省支撑"，不会告诉你"孔轴是不是躺平了"或者"这跟受力方向合不合"。默认朝向能接受（孔轴大致水平、层与层的堆叠方向不垂直于主要受力方向）就往下走；不能接受就用 `set` 手工指定 `print_up`，把孔轴摆成水平。

### arrange · studio_arrange
`mode: auto`：多件放不下自动开新盘。过的标准：`readiness` 里 `arrange` 为 `pass`。

### export · studio_export
逐盘检查 `unmatched_parts`、`bambu_moved_objects`；`mechanical` 档的工艺覆盖（`wall_loops=4`、`sparse_infill_density=20%`、`support_on_build_plate_only=1`）应该在返回里能看到。任一异常如实转述；工艺覆盖没生效（比如被手工 `set` 覆盖掉了）要提醒用户这已经不是默认的结构强度档位。

### check · studio_check
**没跑这一步就不要报克数和时长**。看每盘的 `grams`、`seconds`、`warnings`。**这里的 warnings 只是 Bambu Studio 自己给的通用提示，不是逐个孔查支撑有没有长进去**——真要确认承力孔干净，还得让用户自己看一眼切片预览，本配方现有的工具做不到这么细，如实说明这个边界。

### deliver · studio_send_to_bambu
多盘默认只打开第 1 盘，其余盘路径完整列给用户。`loaded` 恒为 `unverified`，只能说"已请求打开"。

## 我们踩过的坑
- 一批合页/双支承类关节试装配案例里，封闭的承力孔一开始沿轴竖着放，命中 633 段孔内支撑；只是把朝向改成横放、换成普通支撑，封闭孔内的支撑就清零了——但两处开放槽仍然需要装配前手动清理，不是所有"支撑命中"都算数，开放槽和真正的孔内堵塞要分开看（fdm_preprint/gallery_joints_030/RESULTS.md）。
- 同一批机械关节件按 0.25 mm 支撑包络逐件核对孔、槽内有没有残留支撑走线——这种逐孔核查现在的 `studio_check` 做不到，它只返回 Bambu 自己给的通用 warnings（fdm_preprint/mechanical_joints_035/README.md）。
- `mechanical` 档的 4 层壁、20% 填充、`support_on_build_plate_only=1` 不是随手选的默认值：功能件要结构强度，而且支撑面一般在底部，不希望支撑长在侧面破坏配合面的表面质量（print_prep/shape_table.py）。

## 收口时告诉用户
- 载入了几件、有没有告警。
- 最终朝向是不是手工指定的；如果是，为什么默认朝向不能接受（孔轴方向/受力方向）。
- 分了几盘、工艺预设（mechanical 档：0.20 mm 层高、4 层壁、20% 填充）与耗材预设，工艺覆盖有没有生效。
- 有没有试切：跑了就报克数和时长，没跑就说没估算；提醒 warnings 不等于逐孔支撑核查。
- 请求 Bambu Studio 打开了哪个工程文件，其余盘的文件路径给全。

## 出处
- fdm_preprint/gallery_joints_030/RESULTS.md（2026-09-16）
- fdm_preprint/mechanical_joints_035/README.md（2026-09-17）
- print_prep/shape_table.py（2026-09-19）
