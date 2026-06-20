from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "bin",
    "obj",
    "target",
}

IMPORTANT_FILES = {
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    "angular.json",
    "vite.config.ts",
    "next.config.js",
    "next.config.ts",
    "Dockerfile",
    "docker-compose.yml",
    "Program.cs",
    "appsettings.json",
    "pom.xml",
    "build.gradle",
}

@dataclass(frozen=True)
class ProjectFile:
    path: str
    extension: str
    size_bytes: int

@dataclass(frozen=True)
class ProjectScanResult:
    root: str
    total_files_seen: int
    files: list[ProjectFile]
    important_files: list[str]
    directories: list[str]
    detected_stacks: list[str]

def scan_workspace(root: Path, max_files: int = 200) -> ProjectScanResult:
    resolved_root = root.resolve()

    if not resolved_root.exists():
        raise FileNotFoundError(f"Workspace path does not exist: {resolved_root}")

    if not resolved_root.is_dir():
        raise NotADirectoryError(f"Workspace path is not a directory: {resolved_root}")

    files: list[ProjectFile] = []
    important_files: list[str] = []
    directories: set[str] = set()
    total_files_seen = 0

    for path in resolved_root.rglob("*"):
        relative_path = path.relative_to(resolved_root)

        if _should_ignore(relative_path):
            continue

        if path.is_dir():
            directories.add(str(relative_path))
            continue

        if not path.is_file():
            continue

        total_files_seen += 1

        relative_path_str = str(relative_path).replace("\\", "/")

        if path.name in IMPORTANT_FILES or path.suffix == ".csproj":
            important_files.append(relative_path_str)

        if len(files) < max_files:
            files.append(
                ProjectFile(
                    path=relative_path_str,
                    extension=path.suffix.lower(),
                    size_bytes=path.stat().st_size,
                )
            )

    detected_stacks = detect_stacks(
        files=files,
        important_files=important_files,
    )

    return ProjectScanResult(
        root=str(resolved_root),
        total_files_seen=total_files_seen,
        files=files,
        important_files=sorted(important_files),
        directories=sorted(directories),
        detected_stacks=detected_stacks,
    )


def detect_stacks(files: list[ProjectFile], important_files: list[str]) -> list[str]:
    file_paths = {file.path for file in files}
    extensions = {file.extension for file in files}
    important = set(important_files)

    stacks: list[str] = []

    if "pyproject.toml" in important or "requirements.txt" in important or ".py" in extensions:
        stacks.append("Python")

    if "package.json" in important:
        stacks.append("Node.js / JavaScript")

    if "angular.json" in important:
        stacks.append("Angular")

    if "next.config.js" in important or "next.config.ts" in important:
        stacks.append("Next.js")

    if ".ts" in extensions:
        stacks.append("TypeScript")

    if ".cs" in extensions or any(path.endswith(".csproj") for path in important):
        stacks.append(".NET / C#")

    if "Program.cs" in important:
        stacks.append("ASP.NET Core candidate")

    if "pom.xml" in important or "build.gradle" in important or ".java" in extensions:
        stacks.append("Java")

    if "Dockerfile" in important or "docker-compose.yml" in important:
        stacks.append("Docker")

    if not stacks:
        stacks.append("Unknown")

    return _unique(stacks)


def _should_ignore(relative_path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in relative_path.parts)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))

def format_workspace_context(scan: ProjectScanResult, max_files) -> str:
    important_files = "\n".join(f"- {path}" for path in scan.important_files) or "- none"

    directories = "\n".join(f"- {path}" for path in scan.directories[:50]) or "- none"

    files = "\n".join(
        f"- {file.path} ({file.size_bytes} bytes)"
        for file in scan.files[:max_files]
    ) or "- none"

    stacks = "\n".join(f"- {stack}" for stack in scan.detected_stacks)

    return f"""
Workspace root:
{scan.root}

Detected stacks:
{stacks}

Summary:
- Files seen: {scan.total_files_seen}
- Files included in context: {min(len(scan.files), max_files)}
- Directories found: {len(scan.directories)}

Important files:
{important_files}

Directories:
{directories}

Files:
{files}
""".strip()
