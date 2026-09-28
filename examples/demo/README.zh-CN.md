> English: [README.md](README.md)

# 演示资产：五件套马克杯

`examples/head-shell/` 绑定的源 STL 由使用者自己提供，不随插件分发。本目录是
可分发的替代品：一个完全由 `make_demo_parts.py` 生成的小型玩具物体。不含任何
第三方模型数据：每个顶点都由这个脚本生成，所以它的许可就跟仓库本身一致（没有单独的许可）。

## 构建

```
uv run python examples/demo/make_demo_parts.py --out examples/demo/out
```

确定性生成（无随机数、无时间戳）：跑两遍字节完全一致。脚本会打印一份 JSON
摘要，并在 `<out>/` 下写出：

- `parts/body.stl`、`parts/handle.stl`、`parts/lid.stl`、`parts/knob.stl`、
  `parts/base.stl` —— 毫米、Z 朝上，每个都各自水密
- `demo-parts.glb` —— 同样五个部件合成一个文件，每个部件一个命名节点
  （`body`/`handle`/`lid`/`knob`/`base`）

## 载入

**编辑工作区：** 在工作台界面里导入 `demo-parts.glb`，或者让 AI 来做：

```
studio_edit {"action": "import", "expected_revision": <workbench.revision，新工作区填 0>, "params": {"files": ["<abs>/demo-parts.glb"]}}
```

**打印工作区：** 直接载入 STL 部件：

```
studio_load {"files": [
  "<abs>/parts/body.stl", "<abs>/parts/handle.stl", "<abs>/parts/lid.stl",
  "<abs>/parts/knob.stl", "<abs>/parts/base.stl"
]}
```
