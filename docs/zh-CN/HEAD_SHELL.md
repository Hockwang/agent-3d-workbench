> English: [../HEAD_SHELL.md](../HEAD_SHELL.md)

# 工作台内置能力：角色头壳制作

2026-09-22。范围是「已有角色模型 → 可调头壳样稿」。沿用工作台内置 recipes、task templates 和 observation，不另建个人 Codex skill，也不增加用户目录配方副本。

## 入口和实现

`recipes/wearable-head-shell/recipe.json` 与 `guide.md` 提供内置流程；`studio/core/head_shell.py` 是参数化模板，`head_shell_audit.py` 检查装配，`head_shell_vision.py` 生成局部观察网/嘴缝，`head_shell_sight.py` 检查声明眼点。`scikit-image` 为内壁体素重建依赖。`head_shell_audit.py` 的几何内核已拆成独立函数 `audit_parts`，同时以 `removal-audit` 任务模板对外开放，任意一组水密 STL 部件（不限于头壳）都能拿到同一套离散拆卸/装配顺序检查。

工作台启用配方后打开生成模板，六项检查分别显示。来源/结果观察对照从当前生成的已登记产物创建。任务的「修改参数」从冻结输入重建，保留旧版本；前一版人工外观评价不带入新版本。

`studio/core/task_recipe_progress.py` 将进度绑定任务 ID、检查报告 SHA 和观察资产 SHA；缺证据、错版本、失败或被修改的产物不能显示完成。人工 good 评价只代表外观确认，AI 评价单列。任务启动成功后附属配方记录失败应返回 warning，避免误导调用者重复启动。

继续使用 0.7 的 `workspace_id=当前 Codex 任务 ID` 隔离机制；不修改其他任务/legacy 工程。

## 参数与保护约定

输入须是一个静态、闭合且正体积的模型，模板不隐式修复；Z 向上、脸朝 -Y。按总宽缩放、XY 居中、底面归零后，所有局部点位使用 mm。头围是声明的近似包络输入，不可当作实际眼位测量。

默认 `preserve_eye_outline=true` 拒绝 `extension_outline_xz_mm`。眼网在原眼内留边，白高光保持独立件。眼形冲突必须先反馈，不能为自动通过视线检查改变用户表情。嘴形/通风位置需明确参数；没有通用人脸语义识别。

源色件按闭合连通部件处理；名称、颜色、眼网和局部坐标方案绑定来源 SHA。STL 不含原颜色，颜色是明确分件计划。贴图丢失需要显式 `allow_material_loss`。模板预置 600 mm 头围、Ø6×3 mm 磁铁仅作可调初值。

## 证据与成熟度

报告将水密/装配、头部包络、视线、实物试戴分开，`wearable_ready` 固定 false。几何通过并不代表真人可戴。装配路径与视线均为有限采样；局部最小壁厚、通风量、衬垫舒适度和磁力保持尚未完成实物验证。

`inspection/` 是检查资产，不能混入打印 BOM。主模型为根目录 `scene.glb`，主 STL 为根目录零件。

Pikachu 案例：60 cm、4 对 Ø6×3 mm 磁铁、11 件；恢复完整圆眼与闭嘴，网孔藏原黑眼。暂定眼点仍被黄色脸壳遮挡，视线必须待解决。案例参数见 `examples/head-shell/pikachu-round-eyes.json`；不能外推到任意角色或直接作为最终佩戴尺寸。
