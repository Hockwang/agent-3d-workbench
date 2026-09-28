# 机械件加铰链滑轨

## 什么时候用
- 模型有明确的机构角色：箱盖、转台、抽屉、挖掘臂之类，不是人形摆姿势。
- 有关节描述文件（URDF）或能说清哪里转、哪里滑、行程大概多少。
- 允许把五金件（销、螺钉、轴套）和打印件分开列清单、分开算。

## 什么时候别用
- 造型是人形或生物、目的是摆姿势 —— 改用 `poseable-figure`，那边判断点是姿势和外观遮挡，不是机构行程。
- 还没有网格，只有一张参考图 —— 先由 Agent 使用本地 CAD/Blender 建模，或导入用户已有资产，再回到本配方。

## 路线与判断点

### model · studio_load
要定：源文件声明的朝上轴（比如写着 y-up）要不要信；先用实测几何核对一遍。
看哪个数：`readiness.model`；把朝向核对的结论（信了还是改了）记下来，供后面 orient 步骤用。
不过怎么办：几何和声明对不上时，按实测几何走，不要因为文件写了什么就照抄。

### joint · studio_task#install-joint

调用 `studio_task(action="start", template="install-joint")`，明确两个主体、`center_mm`、`axis`、`x_hint`、`anchors_mm` 和 `machining_box_mm`。支持 `pin_hinge`、`slew`、`slider`、`ball_socket` 四族。球窝采用可拆上盖与螺栓，销铰需要 M2 五金；滑轨无端部限位。

检查每件闭合连通、静止交叠、加工区外改动体积，五金与打印件分别列出。交付的 `assembly.urdf` 绑定本次加工 STL，用它继续检查运动；不是把旧模型 URDF 当新结果。只生成数字样件，不宣称姿态保持、强度或实物装配已验收。

### joint · studio_task#motion-check

调用 `studio_task(action="start", template="motion-check")`，输入本次输出的 `assembly.urdf`。默认 `sampling="grid"`，每轴 5 点；也可提供 `sampling="explicit"` 与完整 `configurations`。最多 4096 个组合；超限明确拒绝，不降采样。角度用弧度、位移用米。

读取 `motion-check.json`：每个姿态的 `collisions`、`clear_configurations`、`sampled_clear_values`。各轴无碰撞值不能随意重组为安全区间；未覆盖采样点之间的连续碰撞、防脱、摩擦或实物配合。遇碰撞由 Agent 修改计划/范围并重新检查，不自动把失败改成通过。

### connect · studio_task#removal-audit

输入本次加工输出的闭合 STL，明确分组、安装顺序和每件取出方向，读取离散路径的交叠报告。受阻时修改装配计划再验；不把静止无相交当作装得进去。五金安装和实物配合另验。此任务不读取切片支撑；孔内支撑和开放槽支撑须在切片后人工复核。

### connect · studio_task#joint-coupon（可选）
要定：先打关节试片核对间隙松紧，再打整机。
看哪个数：试片切片是否成功；实际松紧、保持扭矩要人手工用测力计记录，工具给不出这些。

### orient · studio_orient
要定：结构件多数用 flat 贴床更稳，明显悬空的部位（比如伸出去的臂）要不要手工指定朝向。
看哪个数：`warnings` 里有没有 `unstable_contact`。

### arrange · studio_arrange
要定：五金件和打印件要不要分开摆盘，间距够不够留清支撑的空间。
看哪个数：`readiness.arrange`，`unmatched_parts` 是否为空。

### export · studio_export
要定：mechanical 档位默认的 4 层壁、20% 填充够不够这个机构的负载，要不要覆盖。
看哪个数：`unmatched_parts`、`project_3mf` 是否生成成功。

### check · studio_check（可选）
要定：跑不跑试切估算。
不过怎么办：没跑就说没估算。

### deliver · studio_send_to_bambu
要定：先打试片还是直接打整机；多盘时默认只开第一盘。
看哪个数：`loaded` 恒为 `unverified`，只能说已请求打开。

## 我们踩过的坑
- 源文件写着 y-up，实测几何（履带底面、驾驶室高度、回转轴）其实是 z-up——朝上轴要实测，不能照抄文件字段（fdm_preprint/gallery_joints_030/EXCAVATOR_RESULTS.md）。
- 单轴分别扫都通过，组合起来扫才测出 19 处碰撞：一个关节的行程要在其它关节联动的姿态下复核，行程从 −0.7~+0.9 rad 收窄到 −0.7~+0.55 rad（同上）。
- 大范围凸包扫掠去料会把真实几何间的空隙也一起挖掉：对碰撞检查保守，但会过度损伤外观；应该按局部实测接触逐段去料，不是先套一个大半径圆柱（fdm_preprint/docs/mechanical-joint-library-playbook.md）。
- 数字检查（水密、运动、装配、切片）全过，外观仍然可能不合格：按抽屉包围盒挖内腔切穿了正面浮雕，所有门禁都放行了，图审才发现问题——外观要单独图审，不能只看数字门禁（fdm_preprint/gallery_joints_030/WHOLE_RESULTS.md）。
- “装得进去”要按真实插装顺序验（先插活动件、再装销/端帽），终态无碰撞不能替代装配路径检查（同上）。
- 运动副（转/滑）、保持结构（摩擦/分档/驱动）、安装外观三件事是三个不同的职责，不要用一个越来越大的圆盘铰链同时兼顾三者（fdm_preprint/docs/mechanical-joint-library-playbook.md）。

## 收口时告诉用户
- 选了哪个关节族（销铰/回转支承/滑轨/伸缩连杆），装在哪个位置。
- 行程范围是不是被组合姿态碰撞检查收窄过，改了多少。
- 五金件清单和打印件清单分别是什么；有没有打试片，实测间隙/保持扭矩一律说“未验证”。
- 分了几盘、每盘克数和时长（只有跑过 check 才报）。
- 明确没做的事：外观图审、实物配合、长期负载与磨损。

## 出处
- fdm_preprint/gallery_joints_030/EXCAVATOR_RESULTS.md（2026-09-17）：声明轴与实测轴不一致，组合检查比单轴检查多测出碰撞。
- fdm_preprint/docs/mechanical-joint-library-playbook.md（2026-09-17）：8 类选型族、三职责分离、去料要按实测接触算。
- fdm_preprint/mechanical_joints_035（2026-09-17）：三类参数化生成器，局部实测接触避让，试片先行。
- fdm_preprint/gallery_joints_030/WHOLE_RESULTS.md（2026-09-17）：数字门禁全过仍可能外观不合格；装配要按真实插装顺序验。
