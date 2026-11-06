# plugins/ — FYAgent 插件目录

FYAgent 的第三个扩展点。三条路径各管一件事，互不替代：

| 扩展点 | 位置 | 适合什么 | 代价 |
|--------|------|----------|------|
| **插件 Plugin** | `plugins/<名字>/` | 本机想加的**确定性代码**能力（工具 + 提示片段），同进程执行 | 写 Python，重启生效 |
| 技能 Skill | `.agents/skills/<名字>/SKILL.md` | 教会模型**怎么做**（流程、规范、提示词），不写代码 | 纯 Markdown |
| MCP Server | `.agents/skills/.mcp.json` | 跨进程 / 跨机器的服务（数据库、外部 API） | 起服务、配传输 |

## 一个插件长什么样

```
plugins/
└── my-plugin/
    ├── FYPLUGIN.json      ← 必需：清单
    └── tools.py           ← 必需：入口（清单里可改名）
```

`FYPLUGIN.json`：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "一句话说明这个插件干什么",
  "author": "WXHZZL",
  "entry": "tools.py",
  "enabled": true
}
```

| 字段 | 必需 | 说明 |
|------|:----:|------|
| `name` | ✅ | 插件名，不能含 `/`、`\`、`..`；重名只保留先扫到的那个 |
| `description` | — | `/plugins` 与边栏里显示 |
| `version` | — | 仅展示 |
| `entry` | — | 入口文件名，默认 `tools.py` |
| `enabled` | — | `false` 时跳过装载（不删文件也能关） |

`tools.py` 只要暴露一个 `register(api)`：

```python
def hello(name: str) -> dict:
    return {"ok": True, "greeting": "你好，%s" % name}

def register(api):
    api.add_tool(
        name="hello",
        description="向某人打招呼",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "对方的名字"}},
            "required": ["name"],
        },
        handler=hello,
    )
    api.add_prompt("The my-plugin plugin is loaded: use hello to greet someone.")
```

- `api.add_tool(...)` → 挂进与内置工具同一张注册表，模型看到的是普通 Function Calling；
- `api.add_prompt(...)` → 追加到 System Prompt 末尾，告诉模型插件已就绪、何时该用；
- 处理函数返回 `str` 或可 JSON 化的对象/dict 都行；返回 `{"ok": false, ...}` 会被标记为失败。

## 装载与隔离规则

- 启动时同步装载：扫描清单 → `import` 入口 → 调用 `register(api)`。**一个插件报错只影响它自己**，
  其余插件与内置工具照常可用（与 MCP 的策略一致）。
- 插件名或工具名与内置工具、MCP 工具重名时，**先注册者赢**，插件的工具被跳过（`/plugins` 里可见原因）。
- 插件代码在本机 Python 进程内执行，信任等级等同于你自己跑的脚本：FYAgent 不做沙箱。
  只装你信任的插件。
- 文件工具与 `RunCli` 的沙箱仍然只约束内置工具，不约束插件——插件自己负责路径校验
  （参考 `workspace-stats`：统计范围限制在仓库根之内）。

## 开关与配置（`Agent/FYAgent/config.ini`）

```ini
[plugins]
enabled  = true                 # 总开关；false 时完全不扫描不装载
roots    = D:\extra-plugins     # 额外插件根目录，分号分隔；留空 = <仓库根>/plugins
disabled = example-tools        # 停用名单（大小写不敏感），不用删文件
```

临时覆盖用环境变量：

```powershell
$env:FY_PLUGINS = "off"                       # 本次运行关掉全部插件
$env:FY_PLUGIN_DIRS = "D:\my-plugins;E:\team" # 追加扫描目录
```

## 随仓库附带的两个示例

| 插件 | 提供工具 | 演示点 |
|------|----------|--------|
| [`example-tools`](example-tools/tools.py) | `envProbe`、`ping` | 最小写法：加工具 + 加提示片段 |
| [`workspace-stats`](workspace-stats/tools.py) | `workspaceStats` | 有用的默认参数、路径沙箱口径、榜单返回结构 |

## 在 FYAgent 里查看

```
/plugins          插件根目录、每个插件的状态/版本/工具、被跳过的目录
/tools            全部工具（插件工具混在里面，按注册顺序）
Ctrl+B            收起/展开右侧「服务与扩展」边栏（MCP / 插件 / 技能三段）
```

新增插件后**需要重启 FYAgent**（装载只发生在会话创建时）。
