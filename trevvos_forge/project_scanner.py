import ast
import json
from pathlib import Path
from typing import Any

from trevvos_forge.cli_regression_check import extract_argparse_subcommands


SCHEMA_VERSION = "1.0"
PROFILE_PATH = ".trevvos/project_profile.json"
IGNORED_DIRS = {
    ".git",
    ".trevvos",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "bin",
    "obj",
}
MAX_FILE_SIZE = 200_000


def scan_project(repo_root: Path) -> dict:
    root = repo_root.resolve()
    files = _iter_project_files(root)
    paths = [path.relative_to(root).as_posix() for path in files]
    path_set = set(paths)

    python_files = sorted(path for path in paths if path.endswith(".py"))
    package_json = root / "package.json"
    sln_files = sorted(path for path in paths if path.endswith(".sln"))
    csproj_files = sorted(path for path in paths if path.endswith(".csproj"))

    languages = _languages(paths, package_json, sln_files, csproj_files)
    python_profile = _python_profile(root, python_files)
    node_profile = _node_profile(package_json)
    dotnet_profile = _dotnet_profile(sln_files, csproj_files)

    test_directories = sorted(
        directory
        for directory in {"tests", "test"}
        if (root / directory).is_dir()
    )
    test_files = sorted(
        path
        for path in paths
        if path.endswith(".py")
        and (Path(path).name.startswith("test_") or Path(path).name.endswith("_test.py"))
    )
    docs_files = sorted(path for path in paths if Path(path).name.lower() in {"readme.md", "readme.txt"} or path.endswith(".md"))
    config_files = sorted(
        path
        for path in paths
        if Path(path).name
        in {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "Pipfile",
            "poetry.lock",
            "tsconfig.json",
            "vite.config.ts",
            "vite.config.js",
            "next.config.js",
            "next.config.ts",
        }
    )
    build_files = sorted(path for path in paths if path.endswith((".sln", ".csproj")) or Path(path).name == "package.json")
    entrypoints = _entrypoints(root, python_files)

    suggested_test_commands = _suggested_test_commands(
        root=root,
        python_files=python_files,
        test_directories=test_directories,
        test_files=test_files,
        node_profile=node_profile,
        dotnet_profile=dotnet_profile,
    )
    suggested_build_commands = _suggested_build_commands(node_profile, dotnet_profile)

    profile = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "languages": languages,
        "frameworks": _frameworks(path_set),
        "package_managers": _package_managers(path_set),
        "source_files": _source_files(paths),
        "entrypoints": entrypoints,
        "test_directories": test_directories,
        "test_files": test_files,
        "docs_files": docs_files,
        "config_files": config_files,
        "build_files": build_files,
        "suggested_test_commands": suggested_test_commands,
        "suggested_build_commands": suggested_build_commands,
        "summary": _summary(languages, entrypoints),
    }

    if python_profile["modules"]:
        profile["python"] = python_profile
    if node_profile:
        profile["node"] = node_profile
    if dotnet_profile:
        profile["dotnet"] = dotnet_profile

    return profile


def save_project_profile(repo_root: Path, profile: dict) -> Path:
    path = repo_root.resolve() / PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_project_profile(repo_root: Path) -> dict | None:
    path = repo_root.resolve() / PROFILE_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def render_project_profile(profile: dict) -> str:
    return "\n".join(
        [
            "Project profile",
            "",
            f"Summary: {profile.get('summary', 'unknown')}",
            f"Languages: {_join(profile.get('languages'))}",
            f"Entrypoints: {_join(profile.get('entrypoints'))}",
            f"Source files: {_join(profile.get('source_files'))}",
            f"Test directories: {_join(profile.get('test_directories'))}",
            f"Test files: {_join(profile.get('test_files'))}",
            f"Suggested test commands: {_join(profile.get('suggested_test_commands'))}",
            f"Suggested build commands: {_join(profile.get('suggested_build_commands'))}",
        ]
    ).rstrip() + "\n"


def build_project_profile_prompt_section(profile: dict) -> str:
    return "Project profile:\n\n```json\n" + json.dumps(profile, indent=2, ensure_ascii=False) + "\n```"


def _iter_project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def _languages(paths: list[str], package_json: Path, sln_files: list[str], csproj_files: list[str]) -> list[str]:
    languages: list[str] = []
    if any(path.endswith(".py") for path in paths) or any(Path(path).name in {"pyproject.toml", "requirements.txt", "setup.py"} for path in paths):
        languages.append("python")
    if package_json.exists() or any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in paths):
        languages.append("javascript/node")
    if sln_files or csproj_files or any(path.endswith(".cs") for path in paths):
        languages.append("csharp/dotnet")
    return languages or ["unknown"]


def _python_profile(root: Path, python_files: list[str]) -> dict:
    modules: dict[str, Any] = {}
    for relative_path in python_files:
        path = root / relative_path
        if path.stat().st_size > MAX_FILE_SIZE:
            continue
        try:
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (UnicodeDecodeError, SyntaxError):
            continue
        functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        module: dict[str, Any] = {"functions": functions, "classes": classes}
        commands = extract_argparse_subcommands(content)
        if commands:
            module["argparse"] = {"commands": commands}
        modules[relative_path] = module
    return {"modules": modules}


def _node_profile(package_json: Path) -> dict:
    if not package_json.exists():
        return {}
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"package_json": True, "scripts": {}}
    scripts = payload.get("scripts") if isinstance(payload, dict) else {}
    return {"package_json": True, "scripts": scripts if isinstance(scripts, dict) else {}}


def _dotnet_profile(sln_files: list[str], csproj_files: list[str]) -> dict:
    if not sln_files and not csproj_files:
        return {}
    return {
        "solutions": sln_files,
        "projects": csproj_files,
        "test_projects": [path for path in csproj_files if "test" in Path(path).stem.lower()],
    }


def _entrypoints(root: Path, python_files: list[str]) -> list[str]:
    entrypoints: list[str] = []
    for relative_path in python_files:
        name = Path(relative_path).name
        path = root / relative_path
        content = ""
        if path.stat().st_size <= MAX_FILE_SIZE:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = ""
        if name in {"main.py", "cli.py", "app.py"} or 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content:
            entrypoints.append(relative_path)
    return sorted(set(entrypoints))


def _source_files(paths: list[str]) -> list[str]:
    return sorted(path for path in paths if Path(path).suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".cs"})


def _frameworks(path_set: set[str]) -> list[str]:
    frameworks: list[str] = []
    if any(path.startswith("tests/") or path.startswith("test/") for path in path_set):
        frameworks.append("tests")
    if "vite.config.ts" in path_set or "vite.config.js" in path_set:
        frameworks.append("vite")
    if "next.config.js" in path_set or "next.config.ts" in path_set:
        frameworks.append("next")
    return frameworks


def _package_managers(path_set: set[str]) -> list[str]:
    managers: list[str] = []
    if "package.json" in path_set:
        managers.append("npm")
    if "pyproject.toml" in path_set or "requirements.txt" in path_set:
        managers.append("pip")
    return managers


def _suggested_test_commands(
    *,
    root: Path,
    python_files: list[str],
    test_directories: list[str],
    test_files: list[str],
    node_profile: dict,
    dotnet_profile: dict,
) -> list[str]:
    commands: list[str] = []
    if test_directories or test_files:
        commands.append("python -m unittest discover -s tests" if "tests" in test_directories else "python -m unittest discover")
    elif python_files:
        commands.append("python -m py_compile " + " ".join(python_files[:8]))
    scripts = node_profile.get("scripts") if isinstance(node_profile, dict) else None
    if isinstance(scripts, dict) and "test" in scripts:
        commands.append("npm test")
    if dotnet_profile.get("test_projects"):
        commands.append("dotnet test")
    return commands


def _suggested_build_commands(node_profile: dict, dotnet_profile: dict) -> list[str]:
    commands: list[str] = []
    scripts = node_profile.get("scripts") if isinstance(node_profile, dict) else None
    if isinstance(scripts, dict):
        if "build" in scripts:
            commands.append("npm run build")
        if "lint" in scripts:
            commands.append("npm run lint")
    if dotnet_profile:
        commands.append("dotnet build")
    return commands


def _summary(languages: list[str], entrypoints: list[str]) -> str:
    if "python" in languages and entrypoints:
        return f"Python project with CLI entrypoint {entrypoints[0]}."
    if "javascript/node" in languages:
        return "Node/JavaScript project."
    if "csharp/dotnet" in languages:
        return ".NET/C# project."
    return "Project profile generated from repository files."


def _join(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(str(item) for item in value)
