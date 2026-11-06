"""命令行入口：``python -m tui`` 或安装后的 ``fy``。"""

from __future__ import annotations

import argparse
import os

from core.paths import DEFAULT_CONFIG_PATH, DEFAULT_HISTORY_DIR, DEFAULT_WORKSPACE_ROOT
from core.plugins import ENV_PLUGIN_DIRS
from core.skills import split_skill_roots

from .app import FYAgentApp

# 环境变量里也能放技能根目录：FY_SKILLS_DIRS="D:\\skills;E:\\Plugin\\.agents\\skills"
SKILLS_ENV = "FY_SKILLS_DIRS"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fy", description="FYAgent 终端界面")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="配置文件路径")
    parser.add_argument(
        "--history-dir", default=str(DEFAULT_HISTORY_DIR), help="对话存档目录"
    )
    parser.add_argument(
        "--workspace", default=str(DEFAULT_WORKSPACE_ROOT), help="文件工具沙箱根目录"
    )
    parser.add_argument(
        "--skills-dir",
        action="append",
        dest="skills_dirs",
        metavar="路径",
        help="额外的技能根目录，可重复；默认读 <仓库根>/.agents/skills",
    )
    parser.add_argument(
        "--plugins-dir",
        action="append",
        dest="plugin_dirs",
        metavar="路径",
        help="额外的插件根目录，可重复；默认读 <仓库根>/plugins（FYAgent 新增）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 优先级：--skills-dir（命令行）> FY_SKILLS_DIRS（环境变量）> config.ini 的 [skills] roots
    skill_dirs = list(args.skills_dirs or [])
    if not skill_dirs:
        skill_dirs = split_skill_roots(os.environ.get(SKILLS_ENV, ""))
    # 插件根目录同理：--plugins-dir > FY_PLUGIN_DIRS > config.ini 的 [plugins] roots
    plugin_dirs = list(args.plugin_dirs or [])
    if not plugin_dirs:
        plugin_dirs = split_skill_roots(os.environ.get(ENV_PLUGIN_DIRS, ""))
    app = FYAgentApp(
        config_path=args.config,
        history_dir=args.history_dir,
        workspace_root=args.workspace,
        skill_dirs=skill_dirs or None,
        plugin_dirs=plugin_dirs or None,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())