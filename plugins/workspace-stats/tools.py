"""workspace-stats 插件：给模型一双「看仓库」的眼睛。

``workspaceStats(path?, top?)``：扫描目录（默认 FYAgent 的仓库根），按扩展名
汇总文件数 / 总行数 / 空行数，并挑出最大的几个文件。跳过依赖与产物目录
（node_modules、__pycache__、.venv、dist……），单个文件超过 2 MB 不读内容。

路径限制在仓库根之内：与内置文件工具的沙箱同一口径，越界直接拒绝。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

#: 不进入统计的目录名（依赖、缓存、构建产物）
SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "node_modules", ".git", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".cache", ".agents",
}
#: 扩展名 -> 语言名（其余归到扩展名本身）
LANGUAGE_BY_SUFFIX = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".html": "HTML", ".css": "CSS", ".md": "Markdown",
    ".json": "JSON", ".toml": "TOML", ".ini": "INI", ".yaml": "YAML",
    ".yml": "YAML", ".bat": "Batch", ".ps1": "PowerShell", ".mmd": "Mermaid",
    ".tcss": "Textual CSS", ".txt": "Text", ".go": "Go",
}
MAX_FILE_BYTES = 2 * 1024 * 1024


def _project_root() -> Path:
    # plugins/workspace-stats/tools.py → 上三级 = 仓库根
    return Path(__file__).resolve().parents[2]


def workspace_stats(path: str = "", top: int = 5) -> dict:
    """统计目录内的代码分布；path 受仓库根约束。"""
    root = _project_root()
    target = root if not path else (Path(path) if Path(path).is_absolute() else root / path)
    target = target.resolve()
    # 先判越界再判存在：越界的报错不该泄露外部目录是否存在
    try:
        target.relative_to(root)
    except ValueError:
        return {"ok": False, "error": "只允许统计仓库根 %s 之内的目录" % root}
    if not target.is_dir():
        return {"ok": False, "error": "目录不存在：%s" % target}

    languages: dict[str, dict[str, int]] = defaultdict(
        lambda: {"files": 0, "lines": 0, "blank": 0}
    )
    biggest: list[tuple[int, str]] = []
    total_files = 0
    skipped_dirs = 0

    for file_path in target.rglob("*"):
        if not file_path.is_file():
            continue
        relative_parts = file_path.relative_to(target).parts
        if any(part in SKIP_DIRS for part in relative_parts):
            skipped_dirs += 1
            continue
        total_files += 1
        suffix = file_path.suffix.lower()
        language = LANGUAGE_BY_SUFFIX.get(suffix, suffix or "(无扩展名)")
        entry = languages[language]
        entry["files"] += 1
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        entry["lines"] += len(lines)
        entry["blank"] += sum(1 for line in lines if not line.strip())
        biggest.append((len(lines), str(file_path.relative_to(target))))

    biggest.sort(reverse=True)
    ranked = sorted(
        ({"language": name, **values} for name, values in languages.items()),
        key=lambda item: item["lines"],
        reverse=True,
    )
    limit = max(1, min(int(top or 5), 20))
    return {
        "ok": True,
        "root": str(target),
        "total_files": total_files,
        "skipped_in_dep_dirs": skipped_dirs,
        "languages": ranked[:limit],
        "largest_files": [
            {"path": name, "lines": size} for size, name in biggest[:limit]
        ],
    }


def register(api) -> None:
    api.add_tool(
        name="workspaceStats",
        description="统计仓库（或其中某个目录）的代码分布：按语言的文件数与行数、最大的几个文件",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对仓库根的目录；留空 = 整个仓库",
                },
                "top": {
                    "type": "integer",
                    "description": "各榜单取前几名（1-20，默认 5）",
                },
            },
            "required": [],
        },
        handler=workspace_stats,
    )
    api.add_prompt(
        "The workspace-stats plugin is loaded: call workspaceStats to get a "
        "quick picture of repository languages, file counts and largest files."
    )
