import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from trevvos_forge.exceptions import ApplyError
from trevvos_forge.sessions import ForgeSession


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    patch_path: str
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        return asdict(self)


def check_patch(*, workspace_root: Path, session: ForgeSession) -> None:
    patch_path = session.path / "diff.patch"

    if not patch_path.exists():
        raise ApplyError("Cannot apply: diff.patch not found in session.")

    result = _run_git_apply(
        workspace_root=workspace_root,
        args=["git", "apply", "--check", str(patch_path)],
    )

    if result.returncode != 0:
        raise ApplyError(
            "Patch check failed. The diff may not apply cleanly. "
            f"Git error: {_git_error(result)}"
        )


def apply_patch(*, workspace_root: Path, session: ForgeSession) -> ApplyResult:
    patch_path = session.path / "diff.patch"

    if not patch_path.exists():
        raise ApplyError("Cannot apply: diff.patch not found in session.")

    result = _run_git_apply(
        workspace_root=workspace_root,
        args=["git", "apply", str(patch_path)],
    )

    if result.returncode != 0:
        raise ApplyError(
            "Patch apply failed. "
            f"Git error: {_git_error(result)}"
        )

    return ApplyResult(
        applied=True,
        patch_path=str(patch_path),
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )


def _run_git_apply(*, workspace_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=workspace_root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ApplyError("Cannot apply: git executable was not found.") from exc


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or "unknown git apply error"
