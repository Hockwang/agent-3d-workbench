[English](../PRINT_COLOR_INTENT.md)

# 打印部件颜色

明确的均匀不透明颜色可从 GLB/编辑器保留到打印 STL 副本。STL 本身不含颜色，
相邻清单使用几何 SHA256 绑定颜色；纹理、渐变、透明度、文件名和无色 STL 的默认外观不会被猜成单色。

CLI 可用 `--part-color 'body=#0000FF'`；HTTP/MCP 的 export、prepare 接受
`part_colors: {"body": "#0000FF"}`。显式值优先于源颜色；非法颜色和未知部件名被拒绝。

每盘产生去重色板、从 1 开始的料槽及 `color_mapping`。只修改所选耗材配置副本的颜色，
保留温度等其他设置；试切使用同一组耗材配置。未指定颜色的部件继续使用所选预设默认值。

导出后独立回读实际 Bambu 工程的 `filament_colour`、对象和 volume 的 extruder 分配。
缺失/模糊部件、错误颜色、无效槽位和涂色 volume 会阻断，不能用输入清单充当工程结果。
颜色失败使导出和试切就绪状态失效，原有几何、拓扑与摆放检查继续执行。
`--no-project` 只输出几何和颜色意图，不声称实际工程颜色通过。

本机有 Bambu 与配置目录时，运行：

```bash
uv run pytest tests/test_print_colors.py -m bambu -v
```

测试自行生成蓝底红十字徽章，覆盖独立盘和同盘工程导出，不依赖旧手办模型，也不提交打印。
颜色映射通过不代表 AMS 已配置、耗材已装入、实物颜色、装配或打印成功。
本版验证范围见 [plugin 预览说明](PLUGIN_PREVIEW.md)。
