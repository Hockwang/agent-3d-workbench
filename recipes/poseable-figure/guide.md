# 人偶加可动关节

## 什么时候用
- 输入已经是分好肢段的网格（肩、臂、腿、躯干各自独立）。
- 想让人偶能摆出抬手、迈步、蹲下这类姿势，不只是固定造型。
- 用户明确允许在关节附近局部改形（削薄内罩、外移轴心、加连接座），不要求肢体原封不动。

## 什么时候别用
- 整体还是一块没分件的 mesh —— 这条配方从「已经分好肢段」开始，先去做拆件。
- 机构有明确工程角色（箱盖、抽屉、转台、机械臂）—— 改用 `mechanical-joints`，判断点不一样（那边先测朝上轴、这边先测姿态）。
- 只有一张参考图，还没有网格 —— 先由 Agent 使用本地 CAD/Blender 建模，或导入用户已有资产，再回到本配方。

## 路线与判断点

### model · studio_load
要定：肢段分件是否完整，哪几处连接部位要装关节。
看哪个数：`readiness.model`，以及每件的 `watertight`、`components`。
不过怎么办：如实告诉用户哪几件不水密或分件不完整，不自己去补洞或合并肢段。

### joint · studio_task#install-joint

调用 `studio_task(action="start", template="install-joint")`，明确两个主体、`center_mm`、`axis`、`x_hint`、`anchors_mm` 和 `machining_box_mm`。支持 `pin_hinge`、`slew`、`slider`、`ball_socket` 四族。球窝采用可拆上盖与螺栓，销铰需要 M2 五金；滑轨无端部限位。

检查每件闭合连通、静止交叠、加工区外改动体积，五金与打印件分别列出。交付的 `assembly.urdf` 绑定本次加工 STL，用它继续检查运动；不是把旧模型 URDF 当新结果。只生成数字样件，不宣称姿态保持、强度或实物装配已验收。

### joint · studio_task#motion-check

调用 `studio_task(action="start", template="motion-check")`，输入本次输出的 `assembly.urdf`。默认 `sampling="grid"`，每轴 5 点；也可提供 `sampling="explicit"` 与完整 `configurations`。最多 4096 个组合；超限明确拒绝，不降采样。角度用弧度、位移用米。

读取 `motion-check.json`：每个姿态的 `collisions`、`clear_configurations`、`sampled_clear_values`。各轴无碰撞值不能随意重组为安全区间；未覆盖采样点之间的连续碰撞、防脱、摩擦或实物配合。遇碰撞由 Agent 修改计划/范围并重新检查，不自动把失败改成通过。

### connect · studio_task#removal-audit

输入本次加工输出的闭合 STL，明确分组、安装顺序和每件取出方向，读取离散路径的交叠报告。受阻时修改装配计划再验；不把静止无相交当作装得进去。五金安装和实物配合另验。此任务不读取切片支撑；孔内支撑和开放槽支撑须在切片后人工复核。

### connect · studio_task#joint-coupon（可选）
要定：销铰/回转用 joint-coupon；球窝用 install-joint 制作独立小试件，显式给球径、间隙和锚点。先试配合再打整套。
看哪个数：克数和时长只取切片结果；几何任务不估这些数。插拔力、保持力矩需手工测量记录。
不过怎么办：没打试片就直接打整套，如实告诉用户还没做过实物校准，风险自己担。

### orient · studio_orient
要定：球窝、销头这类贴床面积小的件，要不要手工指定朝向。
看哪个数：`warnings` 里有没有 `unstable_contact`，`top_candidates` 里的备选朝向。

### arrange · studio_arrange
要定：关节模块和造型件是分盘还是同盘，间距够不够留手工清支撑的空间。
看哪个数：`readiness.arrange`，以及返回里实际分了几盘。

### export · studio_export
要定：figurine 档位的层高和支撑够不够撑住薄壁球窝，要不要覆盖某个工艺字段。
看哪个数：`unmatched_parts`、`project_3mf` 是否生成成功。

### check · studio_check（可选）
要定：跑不跑试切估算。
不过怎么办：没跑就说没估算，不要凭经验报克数和时长。

### deliver · studio_send_to_bambu
要定：先打试片还是直接打整套；多盘时只开第一盘，其余盘的工程文件路径列给用户。
看哪个数：`loaded` 恒为 `unverified`，只能说已请求打开，不能说已确认载入。

## 我们踩过的坑
- 外罩开口角度不够会数字通过但装不进去：从 82° 缩到 60° 才真的能装入（fdm_preprint/shell_joints_033）。
- 加工范围只按局部半径挖一圈会漏算真实转子扫掠：肩部实际接触超出预留区域，撞到了衣服；要按转子完整扫掠留加工区（fdm_preprint/joint_library_032）。
- 螺钉/螺母的侧向装配入口被外壳挡住——先验装配路径，别只验零件本身能不能拼上（fdm_preprint/joint_library_032）。
- 髋部抬腿会撞到下垂的手掌、裤腿会互碰——组合姿态检查要显式把邻近肢体当障碍物，只测单个关节自己的行程会漏掉这些（fdm_preprint/joint_library_032）。
- 孔道支撑和开放槽支撑长得像但含义不同：把开放槽误判成孔内失败，会挡掉本该放行的方案（fdm_preprint/articulated_029）。
- 外观罩缩小不等于机构本体缩小：报数字时把两者分开说，别把「取消了一圈大罩子」写成「球窝缩小了」（fdm_preprint/toy_joints_036）。
- 关节靠的是持续接触压力（预紧）保持姿势，不是精密配合的间隙；球窝“包住球”只解决防脱，插入力和磨损后的保持力要靠试片实测（fdm_preprint/docs/poseable-toy-joint-playbook.md）。
- 整体放大模型时，自重力矩按尺寸四次方增长、保持力矩只按三次方增长——不能放大后照抄原关节的尺寸比例（同上）。

## 收口时告诉用户
- 关节用了球窝还是摩擦铰，装在哪几个部位，轴心有没有外移、外移了多少。
- 组合姿态检查覆盖了哪些姿势，行程范围是不是被这次实体碰撞收窄过。
- 有没有打试片；插拔力、保持力、长期磨损一律说“未验证”，不要替用户下结论。
- 分了几盘、每盘克数和时长（只有跑过 check 才报）。
- 明确没做的事：独立脸/独立部件的产品门槛、上色、外观是否达到商品标准。

## 出处
- fdm_preprint/joint_library_032（2026-09-17）：球窝/摩擦铰参数化机构，固定座与活动面分离设计的具体实现和失败记录。
- fdm_preprint/docs/poseable-toy-joint-playbook.md（2026-09-17）：关节六个约束——防脱/限位/摩擦/外观各有职责，姿态保持靠预紧不是精密配合。
- fdm_preprint/shell_joints_033（2026-09-17）：局部改形后轴心外移、内罩缩小才能装入的实测边界。
- fdm_preprint/articulated_029（2026-09-16）：行程上限由实体碰撞复核收窄，孔道支撑与开放槽支撑要分开验。
- fdm_preprint/toy_joints_036（2026-09-17）：外观罩尺寸与机构本体尺寸要分开报，不能混着说“缩小了多少”。
