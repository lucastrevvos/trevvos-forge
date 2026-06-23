import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import typer

from trevvos_forge.apply_patch import apply_patch, check_patch
from trevvos_forge.commit_workflow import extract_patch_paths
from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.diff_validation import validate_diff_patch
from trevvos_forge.exceptions import DiffError, FileChangeOutputError, WorkspaceError
from trevvos_forge.file_change_outputs import (
    ALLOWED_OPERATION_BASED_EDIT_OPERATIONS,
    FileChange,
    FileChangesOutput,
    parse_file_changes_output,
)
from trevvos_forge.context_builder import content_with_line_numbers
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.sessions import (
    ForgeSession,
    create_session,
    update_session_status,
    write_session_json,
    write_session_text,
)
from trevvos_forge.test_generation import (
    ExistingTestsCheck,
    TestGenerationTarget,
    build_existing_tests_check,
    build_selected_files_payload,
    build_test_generation_context,
    build_test_generation_summary,
    build_test_generation_target,
    metadata_for_target,
    raw_response_json,
    select_test_generation_commands,
    target_with_symbols,
    validate_file_changes_are_tests_only,
)
from trevvos_forge.test_runner import CommandSpec, run_test_specs_in_sandbox, write_test_artifacts
from trevvos_forge.test_structure_validation import (
    build_test_import_repair_payload,
    compose_generated_test_contents,
    repair_missing_test_imports,
    repair_unittest_method_indentation,
    validate_file_changes_test_structure,
)
from trevvos_forge.timeline import append_timeline_event
from trevvos_forge.workspace import read_workspace_file


MAX_TEST_FILE_CHARS = 20_000
MAX_GENERATION_RETRIES = 3


class Provider(Protocol):
    def generate(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class TestAddRequest:
    repo_root: Path
    source_path: str
    symbol: str | None
    all_symbols: bool
    test_file: str | None
    unit: bool
    e2e: bool
    write: bool
    yes: bool
    force: bool
    keep_sandbox: bool
    max_generation_retries: int
    max_structure_retries: int
    max_sandbox_retries: int
    timeout: int


@dataclass(frozen=True)
class TestAddResult:
    status: str
    session_id: str
    session_path: Path
    source_path: str
    test_file: str | None
    symbols: list[str]
    files_changed: list[str]
    write_allowed: bool
    applied: bool
    artifacts: dict[str, str]
    message: str
    exit_code: int
    metadata: dict[str, Any]
    prompt_ref: str
    next_command: str | None = None
    test_commands: list[str] | None = None
    command_source: str | None = None
    symbol_selector: dict | None = None
    sandbox_status: str | None = None


def run_tests_add_workflow(
    request: TestAddRequest,
    provider: Provider | None = None,
    provider_factory: Callable[[], Provider] | None = None,
) -> TestAddResult:
    workspace_root = request.repo_root.resolve()
    target = build_test_generation_target(
        workspace_root=workspace_root,
        source_path=Path(request.source_path),
        symbol=request.symbol,
        all_symbols=request.all_symbols,
        requested_test_file=Path(request.test_file) if request.test_file is not None else None,
        e2e=request.e2e,
    )

    command_text = _build_command_text(target=target, write=request.write)
    session = create_session(root=workspace_root, user_request=command_text, command="tests add")
    _record_timeline_event(session, "tests_add_started", command_text, "started")

    prompt_template = get_prompt("test_generation")

    source_content = read_workspace_file(workspace_root, Path(target.source_path), max_chars=MAX_TEST_FILE_CHARS)
    test_path = workspace_root / target.test_file
    test_content = (
        read_workspace_file(workspace_root, Path(target.test_file), max_chars=MAX_TEST_FILE_CHARS)
        if test_path.exists()
        else None
    )
    original_symbols = [symbol.name for symbol in target.symbols]
    existing_tests_check = build_existing_tests_check(target=target, test_file_content=test_content)
    write_session_json(session, "existing_tests_check.json", existing_tests_check.to_dict())

    if not request.force and existing_tests_check.status == "all_covered":
        metadata = metadata_for_target(
            target=target,
            write=request.write,
            prompt_ref=prompt_template.ref,
            status="skipped_existing_tests",
            files_changed=[],
            existing_tests_check=existing_tests_check,
            symbols_original=original_symbols,
            provider_called=False,
            write_allowed=False,
        )
        write_session_json(session, "test_generation_metadata.json", metadata)
        write_session_text(
            session,
            "test_generation_summary.md",
            build_test_generation_summary(
                target=target,
                files_changed=[],
                write=request.write,
                status="skipped_existing_tests",
                existing_tests_check=existing_tests_check,
            ),
        )
        session = update_session_status(session, "skipped_existing_tests")
        _record_timeline_event(
            session,
            "tests_add_existing_tests_skipped",
            command_text,
            "skipped",
            artifacts=["existing_tests_check.json", "test_generation_metadata.json", "test_generation_summary.md"],
            existing_tests_status=existing_tests_check.status,
            provider_called=False,
        )
        artifacts = {
            "existing_tests_check": "existing_tests_check.json",
            "metadata": "test_generation_metadata.json",
            "summary": "test_generation_summary.md",
        }
        message = (
            "[yellow]All detected symbols already appear to have tests.[/yellow]"
            if target.all_symbols
            else f"[yellow]Existing tests appear to cover `{target.symbol.name}`.[/yellow]"
        )
        return TestAddResult(
            status="skipped_existing_tests",
            session_id=session.metadata.id,
            session_path=session.path,
            source_path=target.source_path,
            test_file=target.test_file,
            symbols=original_symbols,
            files_changed=[],
            write_allowed=False,
            applied=False,
            artifacts=artifacts,
            message=message,
            exit_code=0,
            metadata=metadata,
            prompt_ref=prompt_template.ref,
            next_command=target.suggested_test_command,
        )

    if not request.force and target.all_symbols and existing_tests_check.status == "partial":
        missing_names = set(existing_tests_check.symbols_missing)
        target = target_with_symbols(
            target,
            [symbol for symbol in target.symbols if symbol.name in missing_names],
        )

    prompt_context = build_test_generation_context(
        workspace_root=workspace_root,
        target=target,
        source_content=content_with_line_numbers(source_content),
        test_content=content_with_line_numbers(test_content) if test_content is not None else None,
        existing_tests_check=existing_tests_check,
        force=request.force,
    )
    prompt = prompt_template.render(test_generation_context=prompt_context)

    write_session_text(session, "test_generation_prompt.md", prompt)
    write_session_json(
        session,
        "selected_files.json",
        build_selected_files_payload(
            target,
            test_file_size=len(test_content.splitlines()) if test_content is not None else 0,
        ),
    )

    actual_provider = provider if provider is not None else _resolve_provider(provider_factory)
    raw_response = actual_provider.generate(prompt)
    write_session_text(session, "test_generation_raw_response.json", raw_response)
    generation_retries = {"max": request.max_generation_retries, "used": 0, "status": "not_needed"}
    generation_error: dict | None = None
    file_changes: FileChangesOutput | None = None

    while True:
        try:
            write_session_json(session, "test_generation_raw_response_parsed.json", raw_response_json(raw_response))
            file_changes = parse_file_changes_output(raw_response)
            validate_file_changes_are_tests_only(file_changes)
            break
        except (WorkspaceError, DiffError) as exc:
            generation_error = _build_generation_guardrail_error_payload(exc, raw_response)
            write_session_json(session, "test_generation_validation.json", generation_error)
            return _build_generation_guardrail_failure_result(
                session=session,
                target=target,
                prompt_template_ref=prompt_template.ref,
                original_symbols=original_symbols,
                existing_tests_check=existing_tests_check,
                generation_retries=generation_retries,
                guardrail_error=generation_error,
                write=request.write,
                command_text=command_text,
            )
        except Exception as exc:
            if not _is_generation_schema_error(exc):
                raise
            generation_error = _build_generation_error_payload(exc, raw_response)
            _write_generation_error_artifacts(session, generation_error)

            if generation_retries["used"] >= request.max_generation_retries:
                generation_retries["status"] = "failed_after_retries"
                return _build_generation_failure_result(
                    session=session,
                    target=target,
                    prompt_template_ref=prompt_template.ref,
                    original_symbols=original_symbols,
                    existing_tests_check=existing_tests_check,
                    generation_retries=generation_retries,
                    generation_error=generation_error,
                    write=request.write,
                    command_text=command_text,
                    request=request,
                )

            attempt = generation_retries["used"] + 1
            retry_prompt_template = get_prompt("test_generation_schema_retry")
            retry_context = _build_generation_schema_retry_context(
                workspace_root=workspace_root,
                target=target,
                source_content=content_with_line_numbers(source_content),
                test_content=content_with_line_numbers(test_content) if test_content is not None else None,
                existing_tests_check=existing_tests_check,
                previous_raw_response=raw_response,
                generation_error=generation_error,
                force=request.force,
            )
            retry_prompt = retry_prompt_template.render(test_generation_schema_retry_context=retry_context)
            retry_raw_response = actual_provider.generate(retry_prompt)
            generation_retries["used"] = attempt
            raw_response = retry_raw_response

            try:
                write_session_json(session, "test_generation_schema_retry_raw_response_parsed.json", raw_response_json(retry_raw_response))
                file_changes = parse_file_changes_output(retry_raw_response)
                validate_file_changes_are_tests_only(file_changes)
            except (WorkspaceError, DiffError) as retry_guardrail_exc:
                generation_error = _build_generation_guardrail_error_payload(retry_guardrail_exc, retry_raw_response)
                write_session_json(session, "test_generation_validation.json", generation_error)
                return _build_generation_guardrail_failure_result(
                    session=session,
                    target=target,
                    prompt_template_ref=prompt_template.ref,
                    original_symbols=original_symbols,
                    existing_tests_check=existing_tests_check,
                    generation_retries=generation_retries,
                    guardrail_error=generation_error,
                    write=request.write,
                    command_text=command_text,
                )
            except Exception as retry_exc:
                if not _is_generation_schema_error(retry_exc):
                    raise
                retry_error = _build_generation_error_payload(retry_exc, retry_raw_response)
                _write_generation_error_artifacts(session, retry_error)
                retry_metadata = {
                    "attempt": attempt,
                    "status": "failed",
                    "prompt": retry_prompt_template.ref,
                    "error_type": retry_error["error_type"],
                    "message": retry_error["message"],
                    "raw_response_path": "test_generation_schema_retry_raw_response.json"
                    if attempt == 1
                    else f"test_generation_schema_retry_{attempt}_raw_response.json",
                    "error": retry_error,
                }
                _write_generation_retry_artifacts(
                    session=session,
                    attempt=attempt,
                    prompt=retry_prompt,
                    raw_response=retry_raw_response,
                    metadata=retry_metadata,
                )
                generation_error = retry_error
                if generation_retries["used"] >= request.max_generation_retries:
                    generation_retries["status"] = "failed_after_retries"
                    return _build_generation_failure_result(
                        session=session,
                        target=target,
                        prompt_template_ref=prompt_template.ref,
                        original_symbols=original_symbols,
                        existing_tests_check=existing_tests_check,
                        generation_retries=generation_retries,
                        generation_error=generation_error,
                        write=request.write,
                        command_text=command_text,
                        request=request,
                    )
                continue

            retry_metadata = {
                "attempt": attempt,
                "status": "succeeded_after_retry",
                "prompt": retry_prompt_template.ref,
                "error_type": generation_error["error_type"],
                "message": generation_error["message"],
                "file_changes": file_changes.to_dict(),
            }
            _write_generation_retry_artifacts(
                session=session,
                attempt=attempt,
                prompt=retry_prompt,
                raw_response=retry_raw_response,
                metadata=retry_metadata,
            )
            generation_retries["status"] = "succeeded_after_retry"
            break

    assert file_changes is not None
    previous_raw_response = raw_response
    previous_raw_response_parsed = raw_response_json(raw_response)
    current_file_changes = file_changes
    generation_retries["status"] = "succeeded_after_retry" if generation_retries["used"] > 0 else "not_needed"
    structure_validation = validate_file_changes_test_structure(
        workspace_root=workspace_root,
        file_changes=current_file_changes,
        framework=target.framework,
        source_symbols=[symbol.name for symbol in target.symbols],
    )
    import_repair: dict | None = None
    unittest_method_repair: dict | None = None
    structure_retries = {"max": request.max_structure_retries, "used": 0, "status": "not_needed"}

    if structure_validation["status"] == "failed":
        repaired_file_changes, unittest_method_repair = _attempt_deterministic_unittest_method_repair(
            target=target,
            file_changes=current_file_changes,
            structure_validation=structure_validation,
        )
        write_session_json(
            session,
            "test_unittest_method_repair.json",
            _summarize_unittest_method_repair(unittest_method_repair),
        )

        if unittest_method_repair["status"] == "repaired":
            current_file_changes = repaired_file_changes
            structure_validation = validate_file_changes_test_structure(
                workspace_root=workspace_root,
                file_changes=current_file_changes,
                framework=target.framework,
                source_symbols=[symbol.name for symbol in target.symbols],
            )

    if structure_validation["status"] == "failed":
        repaired_file_changes, import_repair = _attempt_deterministic_test_import_repair(
            workspace_root=workspace_root,
            target=target,
            file_changes=current_file_changes,
            structure_validation=structure_validation,
        )
        write_session_json(session, "test_import_repair.json", import_repair)

        if import_repair["status"] == "repaired":
            current_file_changes = repaired_file_changes
            structure_validation = validate_file_changes_test_structure(
                workspace_root=workspace_root,
                file_changes=current_file_changes,
                framework=target.framework,
                source_symbols=[symbol.name for symbol in target.symbols],
            )

    while structure_validation["status"] == "failed" and structure_retries["used"] < request.max_structure_retries:
        attempt = structure_retries["used"] + 1
        retry_result = _run_structure_retry_attempt(
            session=session,
            workspace_root=workspace_root,
            target=target,
            provider=actual_provider,
            attempt=attempt,
            file_changes=current_file_changes,
            structure_validation=structure_validation,
            existing_tests_check=existing_tests_check,
            raw_response=previous_raw_response,
            raw_response_parsed=previous_raw_response_parsed,
            import_repair=import_repair,
        )
        structure_retries["used"] = attempt

        if retry_result["status"] == "hard_failure":
            structure_retries["status"] = "failed_after_retries"
            write_session_json(session, "test_structure_validation.json", structure_validation)
            current_file_changes = retry_result.get("file_changes", current_file_changes)
            break

        current_file_changes = retry_result["file_changes"]
        structure_validation = retry_result["structure_validation"]
        import_repair = retry_result["import_repair"]
        previous_raw_response = retry_result["raw_response"]
        previous_raw_response_parsed = retry_result["raw_response_parsed"]

        if structure_validation["status"] == "passed":
            structure_retries["status"] = "succeeded_after_retry"
            break

    if structure_validation["status"] == "failed":
        if structure_retries["used"] > 0 and structure_retries["status"] != "failed_after_retries":
            structure_retries["status"] = "failed_after_retries"
        elif structure_retries["used"] == 0:
            structure_retries["status"] = "not_needed"

    write_session_json(session, "test_file_changes.json", current_file_changes.to_dict())
    write_session_json(session, "file_changes.json", current_file_changes.to_dict())
    write_session_json(session, "test_structure_validation.json", structure_validation)
    files_changed = [change.path for change in current_file_changes.changes]

    if structure_validation["status"] == "failed":
        metadata = metadata_for_target(
            target=target,
            write=request.write,
            prompt_ref=prompt_template.ref,
            status="failed_test_structure_validation",
            files_changed=files_changed,
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
            structure_validation=structure_validation,
            unittest_method_repair=unittest_method_repair,
            import_repair=import_repair,
            structure_retries=structure_retries,
            symbols_original=original_symbols,
            provider_called=True,
            write_allowed=False,
        )
        write_session_json(session, "test_generation_metadata.json", metadata)
        write_session_text(
            session,
            "test_generation_summary.md",
            build_test_generation_summary(
                target=target,
                files_changed=files_changed,
                write=request.write,
                status="failed_test_structure_validation",
                existing_tests_check=existing_tests_check,
                generation_retries=generation_retries,
                structure_validation=structure_validation,
                unittest_method_repair=unittest_method_repair,
                import_repair=import_repair,
                structure_retries=structure_retries,
            ),
        )
        session = update_session_status(session, "tests_add_failed")
        _record_timeline_event(
            session,
            "tests_add_failed",
            command_text,
            "failed",
            reason="failed_test_structure_validation",
            artifacts=[
                "test_structure_validation.json",
                "test_import_repair.json",
                "test_generation_metadata.json",
                "test_generation_summary.md",
                *(
                    [
                        "test_generation_retry_prompt.md",
                        "test_generation_retry_raw_response.json",
                        "test_generation_retry_metadata.json",
                    ]
                    if structure_retries["used"] > 0
                    else []
                ),
            ],
        )
        return TestAddResult(
            status="tests_add_failed",
            session_id=session.metadata.id,
            session_path=session.path,
            source_path=target.source_path,
            test_file=target.test_file,
            symbols=original_symbols,
            files_changed=files_changed,
            write_allowed=False,
            applied=False,
            artifacts={
                "existing_tests_check": "existing_tests_check.json",
                "prompt": "test_generation_prompt.md",
                "raw_response": "test_generation_raw_response.json",
                "file_changes": "test_file_changes.json",
                "diff": "test_diff.patch",
                "metadata": "test_generation_metadata.json",
                "summary": "test_generation_summary.md",
                "validation": "test_generation_validation.json",
                "structure_validation": "test_structure_validation.json",
                "sandbox_results": "test_sandbox_results.json",
                "sandbox_output": "test_sandbox_output.log",
                **({"unittest_method_repair": "test_unittest_method_repair.json"} if unittest_method_repair is not None else {}),
                **({"import_repair": "test_import_repair.json"} if import_repair is not None else {}),
            },
            message="[red]Generated test file failed structural validation.[/red]"
            if structure_retries["used"] == 0
            else "[red]Generated tests still failed structural validation after retry.[/red]",
            exit_code=1,
            metadata=metadata,
            prompt_ref=prompt_template.ref,
        )

    sandbox_retries = {"max": request.max_sandbox_retries, "used": 0, "status": "not_needed"}
    diff_warnings: list[str] = []
    unified_diff = build_unified_diff_from_file_changes(
        workspace_root=workspace_root,
        file_changes=current_file_changes,
        warnings=diff_warnings,
    )
    write_session_text(session, "test_diff.patch", unified_diff)
    write_session_text(session, "diff.patch", unified_diff)

    validation_result = validate_diff_patch(
        workspace_root=workspace_root,
        session=session,
        diff_text=unified_diff,
    )
    check_patch(workspace_root=workspace_root, session=session)
    validation_payload = validation_result.to_dict()
    validation_payload["git_apply_check"] = "passed"
    validation_payload["test_command"] = target.suggested_test_command
    write_session_json(session, "test_generation_validation.json", validation_payload)
    write_session_json(session, "diff_validation.json", validation_result.to_dict())
    write_session_json(
        session,
        "diff_check.json",
        {"git_apply_check": "passed", "patch_path": str(session.path / "test_diff.patch")},
    )

    test_commands, command_source, symbol_selector = select_test_generation_commands(
        workspace_root=workspace_root,
        target=target,
    )
    command_spec_source = (
        "targeted_test_file"
        if command_source == "targeted"
        else "targeted_symbol"
        if command_source == "targeted_symbol"
        else command_source
    )
    command_specs = [CommandSpec(command=command, source=command_spec_source) for command in test_commands]
    _record_timeline_event(
        session,
        "tests_add_sandbox_started",
        command_text,
        "started",
        test_commands=test_commands,
        command_source=command_source,
        symbol_selector=symbol_selector,
        keep_sandbox=request.keep_sandbox,
    )
    sandbox_result = run_test_specs_in_sandbox(
        repo_root=workspace_root,
        patch_path=session.path / "test_diff.patch",
        command_specs=command_specs,
        timeout_seconds=request.timeout,
        keep_sandbox=request.keep_sandbox,
    )
    write_test_artifacts(session.path, sandbox_result)
    _write_test_sandbox_aliases(
        session.path,
        command_source=command_source,
        symbol_selector=symbol_selector,
    )

    sandbox_metadata = sandbox_result.sandbox or {}
    sandbox_event = "tests_add_sandbox_completed" if sandbox_result.status == "passed" else "tests_add_sandbox_failed"
    _record_timeline_event(
        session,
        sandbox_event,
        command_text,
        "succeeded" if sandbox_result.status == "passed" else "failed",
        reason=None if sandbox_result.status == "passed" else sandbox_result.status,
        artifacts=[
            "test_sandbox_results.json",
            "test_sandbox_output.log",
            "sandbox_test_results.json",
            "sandbox_test_output.log",
        ],
        test_status=sandbox_result.status,
        patch_apply_check=sandbox_metadata.get("patch_apply_check", "unknown"),
        patch_apply=sandbox_metadata.get("patch_apply", "unknown"),
    )

    write_allowed = sandbox_result.status == "passed"
    metadata = metadata_for_target(
        target=target,
        write=request.write,
        prompt_ref=prompt_template.ref,
        status="diff_ready",
        files_changed=[change.path for change in current_file_changes.changes],
        sandbox_status=sandbox_result.status,
        sandbox_commands=test_commands,
        sandbox_command_source=command_source,
        symbol_selector=symbol_selector,
        existing_tests_check=existing_tests_check,
        generation_retries=generation_retries,
        sandbox_retries=sandbox_retries,
        structure_validation=structure_validation,
        unittest_method_repair=unittest_method_repair,
        import_repair=import_repair,
        structure_retries=structure_retries,
        symbols_original=original_symbols,
        provider_called=True,
        write_allowed=write_allowed,
    )
    write_session_json(session, "test_generation_metadata.json", metadata)
    write_session_text(
        session,
        "test_generation_summary.md",
        build_test_generation_summary(
            target=target,
            files_changed=[change.path for change in current_file_changes.changes],
            write=request.write,
            status="diff_ready",
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
            sandbox_retries=sandbox_retries,
            structure_validation=structure_validation,
            unittest_method_repair=unittest_method_repair,
            import_repair=import_repair,
            structure_retries=structure_retries,
        ),
    )

    if sandbox_result.status != "passed" and sandbox_result.status != "timed_out" and request.max_sandbox_retries > 0:
        while sandbox_retries["used"] < request.max_sandbox_retries:
            attempt = sandbox_retries["used"] + 1
            retry_prompt_template = get_prompt("test_generation_sandbox_retry")
            retry_context = _build_sandbox_retry_context(
                workspace_root=workspace_root,
                target=target,
                source_content=content_with_line_numbers(source_content),
                test_content=content_with_line_numbers(test_content) if test_content is not None else None,
                existing_tests_check=existing_tests_check,
                current_file_changes=current_file_changes,
                sandbox_result=sandbox_result,
                sandbox_output=(session.path / "test_sandbox_output.log").read_text(encoding="utf-8"),
                unified_diff=(session.path / "test_diff.patch").read_text(encoding="utf-8"),
                force=request.force,
            )
            retry_prompt = retry_prompt_template.render(test_generation_sandbox_retry_context=retry_context)
            retry_raw_response = actual_provider.generate(retry_prompt)
            sandbox_retries["used"] = attempt
            retry_metadata = {
                "attempt": attempt,
                "status": "failed",
                "prompt": retry_prompt_template.ref,
                "raw_response_path": "test_generation_sandbox_retry_raw_response.json"
                if attempt == 1
                else f"test_generation_sandbox_retry_{attempt}_raw_response.json",
            }

            try:
                retry_file_changes = parse_file_changes_output(retry_raw_response)
                validate_file_changes_are_tests_only(retry_file_changes)
            except Exception as retry_exc:
                if not _is_generation_schema_error(retry_exc):
                    raise
                retry_metadata["error_type"] = "schema_invalid"
                retry_metadata["message"] = str(retry_exc)
                _write_sandbox_retry_artifacts(
                    session=session,
                    attempt=attempt,
                    prompt=retry_prompt,
                    raw_response=retry_raw_response,
                    metadata=retry_metadata,
                )
                if sandbox_retries["used"] >= request.max_sandbox_retries:
                    sandbox_retries["status"] = "failed_after_retries"
                    return _build_sandbox_failure_result(
                        session=session,
                        target=target,
                        prompt_template_ref=prompt_template.ref,
                        original_symbols=original_symbols,
                        files_changed=[change.path for change in current_file_changes.changes],
                        existing_tests_check=existing_tests_check,
                        generation_retries=generation_retries,
                        sandbox_retries=sandbox_retries,
                        unittest_method_repair=unittest_method_repair,
                        write=request.write,
                        command_text=command_text,
                        request=request,
                        message="[red]Sandbox tests failed after retry.[/red]",
                    )
                continue

            retry_structure_validation = validate_file_changes_test_structure(
                workspace_root=workspace_root,
                file_changes=retry_file_changes,
                framework=target.framework,
                source_symbols=[symbol.name for symbol in target.symbols],
            )
            retry_unittest_method_repair: dict | None = None
            retry_import_repair: dict | None = None
            if retry_structure_validation["status"] == "failed":
                repaired_retry_file_changes, retry_unittest_method_repair = _attempt_deterministic_unittest_method_repair(
                    target=target,
                    file_changes=retry_file_changes,
                    structure_validation=retry_structure_validation,
                )
                if retry_unittest_method_repair["status"] == "repaired":
                    retry_file_changes = repaired_retry_file_changes
                    retry_structure_validation = validate_file_changes_test_structure(
                        workspace_root=workspace_root,
                        file_changes=retry_file_changes,
                        framework=target.framework,
                        source_symbols=[symbol.name for symbol in target.symbols],
                    )

            if retry_structure_validation["status"] == "failed":
                repaired_retry_file_changes, retry_import_repair = _attempt_deterministic_test_import_repair(
                    workspace_root=workspace_root,
                    target=target,
                    file_changes=retry_file_changes,
                    structure_validation=retry_structure_validation,
                )
                if retry_import_repair["status"] == "repaired":
                    retry_file_changes = repaired_retry_file_changes
                    retry_structure_validation = validate_file_changes_test_structure(
                        workspace_root=workspace_root,
                        file_changes=retry_file_changes,
                        framework=target.framework,
                        source_symbols=[symbol.name for symbol in target.symbols],
                    )

            retry_structure_retries = {"max": 0, "used": 0, "status": "not_needed"}
            sandbox_retries["status"] = "succeeded_after_retry"
            retry_finalization = _finalize_sandbox_stage(
                session=session,
                workspace_root=workspace_root,
                target=target,
                request=request,
                command_text=command_text,
                prompt_template_ref=prompt_template.ref,
                current_file_changes=retry_file_changes,
                existing_tests_check=existing_tests_check,
                generation_retries=generation_retries,
                structure_validation=retry_structure_validation,
                unittest_method_repair=retry_unittest_method_repair,
                import_repair=retry_import_repair,
                structure_retries=retry_structure_retries,
                original_symbols=original_symbols,
                sandbox_retries=sandbox_retries,
            )
            sandbox_result = retry_finalization["sandbox_result"]
            metadata = retry_finalization["metadata"]
            test_commands = retry_finalization["test_commands"]
            command_source = retry_finalization["command_source"]
            symbol_selector = retry_finalization["symbol_selector"]
            write_allowed = retry_finalization["write_allowed"]
            _write_sandbox_retry_artifacts(
                session=session,
                attempt=attempt,
                prompt=retry_prompt,
                raw_response=retry_raw_response,
                metadata={
                    **retry_metadata,
                    "status": "succeeded_after_retry" if sandbox_result.status == "passed" else "failed",
                    "sandbox_status": sandbox_result.status,
                },
            )
            if sandbox_result.status == "passed":
                sandbox_retries["status"] = "succeeded_after_retry"
                break
            if sandbox_retries["used"] >= request.max_sandbox_retries:
                sandbox_retries["status"] = "failed_after_retries"
                return _build_sandbox_failure_result(
                    session=session,
                    target=target,
                    prompt_template_ref=prompt_template.ref,
                    original_symbols=original_symbols,
                    files_changed=[change.path for change in retry_file_changes.changes],
                    existing_tests_check=existing_tests_check,
                    generation_retries=generation_retries,
                    sandbox_retries=sandbox_retries,
                    unittest_method_repair=retry_unittest_method_repair,
                    write=request.write,
                    command_text=command_text,
                    request=request,
                    message="[red]Sandbox tests failed after retry.[/red]",
                )

    if sandbox_result.status != "passed":
        sandbox_retries["status"] = "failed_after_retries"
        return _build_sandbox_failure_result(
            session=session,
            target=target,
            prompt_template_ref=prompt_template.ref,
            original_symbols=original_symbols,
            files_changed=[change.path for change in current_file_changes.changes],
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
            sandbox_retries=sandbox_retries,
            unittest_method_repair=unittest_method_repair,
            write=request.write,
            command_text=command_text,
            request=request,
            message="[red]Sandbox tests failed.[/red]",
        )

    if not request.write:
        session = update_session_status(session, "test_diff_validated")
        return TestAddResult(
            status="test_diff_validated",
            session_id=session.metadata.id,
            session_path=session.path,
            source_path=target.source_path,
            test_file=target.test_file,
            symbols=original_symbols,
            files_changed=[change.path for change in current_file_changes.changes],
            write_allowed=write_allowed,
            applied=False,
            artifacts={
                "existing_tests_check": "existing_tests_check.json",
                "prompt": "test_generation_prompt.md",
                "raw_response": "test_generation_raw_response.json",
                "file_changes": "test_file_changes.json",
                "diff": "test_diff.patch",
                "metadata": "test_generation_metadata.json",
                "summary": "test_generation_summary.md",
                "validation": "test_generation_validation.json",
                "structure_validation": "test_structure_validation.json",
                "sandbox_results": "test_sandbox_results.json",
                "sandbox_output": "test_sandbox_output.log",
                **({"unittest_method_repair": "test_unittest_method_repair.json"} if unittest_method_repair is not None else {}),
                **({"import_repair": "test_import_repair.json"} if import_repair is not None else {}),
            },
            message=(
                "[green]Test patch generated and validated in sandbox.[/green]"
                if sandbox_result.status == "passed"
                else "[yellow]Test patch generated but sandbox tests failed.[/yellow]"
            ),
            exit_code=0,
            metadata=metadata,
            prompt_ref=prompt_template.ref,
            next_command=target.suggested_test_command,
            test_commands=test_commands,
            command_source=command_source,
            symbol_selector=symbol_selector,
            sandbox_status=sandbox_result.status,
        )

    if not write_allowed:
        _record_timeline_event(
            session,
            "tests_add_write_blocked",
            command_text,
            "failed",
            reason="sandbox_failed",
            artifacts=["test_sandbox_results.json", "test_sandbox_output.log"],
        )
        return TestAddResult(
            status="write_blocked",
            session_id=session.metadata.id,
            session_path=session.path,
            source_path=target.source_path,
            test_file=target.test_file,
            symbols=original_symbols,
            files_changed=[change.path for change in current_file_changes.changes],
            write_allowed=False,
            applied=False,
            artifacts={
                "sandbox_results": "test_sandbox_results.json",
                "sandbox_output": "test_sandbox_output.log",
            },
            message="[red]Cannot write test patch because sandbox tests failed.[/red]",
            exit_code=1,
            metadata=metadata,
            prompt_ref=prompt_template.ref,
            next_command=target.suggested_test_command,
            test_commands=test_commands,
            command_source=command_source,
            symbol_selector=symbol_selector,
            sandbox_status=sandbox_result.status,
        )

    if not request.yes and not typer.confirm("Apply generated test patch to working tree?", default=False):
        session = update_session_status(session, "tests_add_cancelled")
        _record_timeline_event(
            session,
            "tests_add_cancelled",
            command_text,
            "cancelled",
            reason="user_cancelled",
        )
        return TestAddResult(
            status="tests_add_cancelled",
            session_id=session.metadata.id,
            session_path=session.path,
            source_path=target.source_path,
            test_file=target.test_file,
            symbols=original_symbols,
            files_changed=[change.path for change in current_file_changes.changes],
            write_allowed=write_allowed,
            applied=False,
            artifacts={
                "existing_tests_check": "existing_tests_check.json",
                "prompt": "test_generation_prompt.md",
                "raw_response": "test_generation_raw_response.json",
                "file_changes": "test_file_changes.json",
                "diff": "test_diff.patch",
                "metadata": "test_generation_metadata.json",
                "summary": "test_generation_summary.md",
                "validation": "test_generation_validation.json",
                "structure_validation": "test_structure_validation.json",
                "sandbox_results": "test_sandbox_results.json",
                "sandbox_output": "test_sandbox_output.log",
                **({"import_repair": "test_import_repair.json"} if import_repair is not None else {}),
            },
            message="[yellow]Cancelled.[/yellow]",
            exit_code=0,
            metadata=metadata,
            prompt_ref=prompt_template.ref,
            next_command=target.suggested_test_command,
            test_commands=test_commands,
            command_source=command_source,
            symbol_selector=symbol_selector,
            sandbox_status=sandbox_result.status,
        )

    apply_result = apply_patch(workspace_root=workspace_root, session=session)
    write_session_json(session, "test_apply_result.json", apply_result.to_dict())
    session = update_session_status(session, "tests_applied")
    metadata = {**metadata, "status": "applied", "write_allowed": True}
    write_session_json(session, "test_generation_metadata.json", metadata)
    _record_timeline_event(
        session,
        "tests_add_applied",
        command_text,
        "succeeded",
        artifacts=["test_apply_result.json"],
        files_changed=[change.path for change in current_file_changes.changes],
        next_recommended_command=target.suggested_test_command,
    )

    return TestAddResult(
        status="tests_applied",
        session_id=session.metadata.id,
        session_path=session.path,
        source_path=target.source_path,
        test_file=target.test_file,
        symbols=original_symbols,
        files_changed=[change.path for change in current_file_changes.changes],
        write_allowed=True,
        applied=True,
        artifacts={
            "apply_result": "test_apply_result.json",
            "metadata": "test_generation_metadata.json",
        },
        message="[green]Test patch applied successfully.[/green]",
        exit_code=0,
        metadata=metadata,
        prompt_ref=prompt_template.ref,
        next_command=target.suggested_test_command,
        test_commands=test_commands,
        command_source=command_source,
        symbol_selector=symbol_selector,
        sandbox_status=sandbox_result.status,
    )


def render_test_add_result(*, result: TestAddResult, json_output: bool, console: Any) -> None:
    if json_output:
        console.print(json.dumps({**result.metadata, "session_id": result.session_id}, indent=2))
        return

    generation_retries = result.metadata.get("generation_retries", {}) if isinstance(result.metadata, dict) else {}
    generation_retry_used = int(generation_retries.get("used", 0) or 0)
    generation_retry_max = int(generation_retries.get("max", 0) or 0)
    generation_retry_status = generation_retries.get("status")
    sandbox_retries = result.metadata.get("sandbox_retries", {}) if isinstance(result.metadata, dict) else {}
    sandbox_retry_used = int(sandbox_retries.get("used", 0) or 0)
    sandbox_retry_max = int(sandbox_retries.get("max", 0) or 0)
    sandbox_retry_status = sandbox_retries.get("status")

    status = result.status

    if result.status == "skipped_existing_tests":
        console.print(result.message)
        console.print("No new test patch was generated.\n")
        console.print("Use --force to generate additional tests anyway.")
        console.print("\n[bold]Artifacts[/bold]")
        for artifact_key in ["existing_tests_check", "metadata", "summary"]:
            console.print(f"  - {result.session_path / result.artifacts[artifact_key]}")
        return

    if result.status == "tests_add_failed":
        console.print(result.message)
        console.print(f"Review {result.session_path / 'test_structure_validation.json'}.")
        return

    if result.status == "failed_test_generation_schema":
        console.print(result.message)
        error_path = result.session_path / "test_generation_error.json"
        if error_path.exists():
            try:
                error_payload = json.loads(error_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                error_payload = {}
            error_type = error_payload.get("error_type", "unknown")
            operation = error_payload.get("operation")
            field = error_payload.get("field")
            if operation:
                console.print(f"Schema error: {error_type} ({operation})")
            elif field:
                console.print(f"Schema error: {error_type} ({field})")
            else:
                console.print(f"Schema error: {error_type}")
        if generation_retry_used > 0:
            console.print(f"Schema retry used: {generation_retry_used}/{generation_retry_max}")
            if generation_retry_status == "failed_after_retries":
                console.print("Test generation schema failed after retry.")
            elif generation_retry_status == "succeeded_after_retry":
                console.print("Test generation schema retry succeeded.")
        console.print(f"Review {result.session_path / 'test_generation_error.json'}.")
        if generation_retry_used > 0:
            console.print(f"Review {result.session_path / 'test_generation_schema_retry_metadata.json'}.")
        return

    if result.status == "failed_test_generation_guardrail":
        console.print(result.message)
        console.print(f"Review {result.session_path / 'test_generation_validation.json'}.")
        return

    if result.status == "write_blocked":
        console.print(result.message)
        console.print(f"Review {result.session_path / 'test_sandbox_output.log'}.")
        return

    if result.status == "failed_sandbox_after_retries":
        console.print(result.message)
        console.print(f"Review {result.session_path / 'test_sandbox_output.log'}.")
        console.print(f"Review {result.session_path / 'test_generation_sandbox_retry_metadata.json'}.")
        return

    if result.status == "tests_add_cancelled":
        console.print(result.message)
        return

    if result.status == "tests_applied":
        console.print(result.message)
        console.print(f"Session: {result.session_id}")
        console.print(f"Status:  {result.status}")
        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {result.session_path / 'test_apply_result.json'}")
        console.print("\n[bold]Next[/bold]")
        console.print(f"  {result.next_command or 'python -m unittest discover -s tests'}")
        return

    console.print(result.message)
    console.print(f"Session: {result.session_id}")
    console.print(f"Status:  {status}")
    console.print(f"Prompt:  {result.prompt_ref}")
    if generation_retry_used > 0 and generation_retry_status == "succeeded_after_retry":
        console.print(f"Schema retry used: {generation_retry_used}/{generation_retry_max}")
    if sandbox_retry_used > 0:
        console.print(f"Sandbox retry used: {sandbox_retry_used}/{sandbox_retry_max}")
    console.print("\n[bold]Files changed[/bold]")
    for changed_path in result.files_changed:
        console.print(f"  - {changed_path}")
    console.print("\n[bold]Artifacts[/bold]")
    for key in [
        "existing_tests_check",
        "diff",
        "file_changes",
        "validation",
        "structure_validation",
        "summary",
        "sandbox_results",
        "sandbox_output",
        "metadata",
    ]:
        artifact = result.artifacts.get(key)
        if artifact is not None:
            console.print(f"  - {result.session_path / artifact}")
    console.print("\n[bold]Validations[/bold]")
    console.print("  - test-file-only safety validation: passed")
    console.print("  - test structure validation: passed")
    console.print("  - git apply --check: passed")
    console.print(f"  - sandbox tests: {result.sandbox_status}")
    console.print("\n[bold]Test commands[/bold]")
    for index, command in enumerate(result.test_commands or [], start=1):
        console.print(f"  {index}. {command}")
        console.print(f"     source: {result.command_source}")
        if not result.symbol_selector or not result.symbol_selector.get("enabled", False):
            console.print(f"     symbol selector: disabled ({(result.symbol_selector or {}).get('reason', 'unknown')})")
    console.print("\n[bold]Next[/bold]")
    if generation_retry_used > 0 and generation_retry_status == "succeeded_after_retry":
        console.print("  Test generation schema retry succeeded.")
    if sandbox_retry_used > 0:
        if sandbox_retry_status == "succeeded_after_retry":
            console.print("  Test generation sandbox retry succeeded.")
        elif sandbox_retry_status == "failed_after_retries":
            console.print("  Test generation sandbox retry failed after retry.")
    if result.sandbox_status == "passed":
        console.print(f"  Re-run with `--write` to apply after review, or inspect test_diff.patch.")
    else:
        console.print("  Review test_sandbox_output.log before writing.")


def _build_command_text(*, target: TestGenerationTarget, write: bool) -> str:
    command_text = f"trevvos tests add {target.source_path}"
    if target.all_symbols:
        command_text += " --all"
    elif target.symbol is not None:
        command_text += f" --symbol {target.symbol.name}"
    if target.test_file is not None:
        command_text += f" --test-file {target.test_file}"
    if write:
        command_text += " --write"
    return command_text


def _resolve_provider(provider_factory: Callable[[], Provider] | None) -> Provider:
    if provider_factory is None:
        raise DiffError("Provider factory is required when a provider instance is not supplied.")

    return provider_factory()


def _is_generation_schema_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        isinstance(exc, FileChangeOutputError)
        or "Unknown operation at changes" in message
        or "Missing or invalid list field: changes" in message
        or "File changes output must contain at least one change" in message
        or "full_file_rewrite must be used as mode with content" in message
        or "The model returned invalid JSON for file changes" in message
        or "does not contain a valid JSON object" in message
        or "Missing or invalid string field: changes[" in message
        or "Invalid item at changes[" in message
    )


def _build_generation_error_payload(exc: Exception, raw_response: str) -> dict:
    message = str(exc)
    payload: dict[str, Any] = {
        "status": "failed",
        "error_type": "invalid_file_change_schema",
        "message": message,
        "raw_response_path": "test_generation_raw_response.json",
        "allowed_operations": sorted(ALLOWED_OPERATION_BASED_EDIT_OPERATIONS),
        "suggested_resolution": "Return only valid JSON with a top-level changes list.",
    }

    unknown_match = re.search(r"Unknown operation at changes\[(\d+)\]\.operation:\s*([^.]+)\.", message)
    if unknown_match:
        operation = unknown_match.group(2).strip()
        payload.update(
            {
                "error_type": "unknown_operation",
                "operation": operation,
                "suggested_resolution": _suggested_resolution_for_operation(operation),
            }
        )
        return payload

    if "Missing or invalid list field: changes" in message:
        payload.update(
            {
                "error_type": "invalid_file_change_schema",
                "field": "changes",
                "suggested_resolution": 'Return a JSON object with a top-level "changes" list.',
            }
        )
        return payload

    if "File changes output must contain at least one change" in message:
        payload.update(
            {
                "error_type": "invalid_file_change_schema",
                "field": "changes",
                "suggested_resolution": 'Return a JSON object with a non-empty top-level "changes" list.',
            }
        )
        return payload

    if "full_file_rewrite must be used as mode with content" in message:
        payload.update(
            {
                "error_type": "invalid_full_file_rewrite_usage",
                "suggested_resolution": "Use mode full_file_rewrite with content, or use an allowed operation_based_edit operation.",
            }
        )
        return payload

    if "The model returned invalid JSON for file changes" in message or "does not contain a valid JSON object" in message:
        payload.update(
            {
                "error_type": "invalid_json",
                "suggested_resolution": 'Return only valid JSON with a top-level "changes" list.',
            }
        )
        return payload

    missing_string_match = re.search(r"Missing or invalid string field: (changes\[\d+\]\.[A-Za-z_]+)", message)
    if missing_string_match:
        payload.update(
            {
                "error_type": "invalid_file_change_schema",
                "field": missing_string_match.group(1),
                "suggested_resolution": _suggested_resolution_for_field(missing_string_match.group(1)),
            }
        )
        return payload

    if "Invalid item at changes[" in message:
        payload.update(
            {
                "error_type": "invalid_file_change_schema",
                "field": "changes",
                "suggested_resolution": 'Return a JSON object with a top-level "changes" list and valid file change objects.',
            }
        )
        return payload

    return payload


def _build_generation_guardrail_error_payload(exc: Exception, raw_response: str) -> dict:
    message = str(exc)
    return {
        "status": "failed",
        "error_type": "test_only_validation",
        "message": message,
        "raw_response_path": "test_generation_raw_response.json",
        "suggested_resolution": "Only include test files and keep production files unchanged.",
        "raw_response": raw_response,
    }


def _suggested_resolution_for_operation(operation: str) -> str:
    if operation == "replace_in_file":
        return (
            "replace_in_file is not a valid operation. Use replace_exact_text or replace_block for replacements, "
            "append_to_file for appending tests, or create_file for new test files."
        )

    return (
        f"{operation} is not a valid operation. Use append_to_file, create_file, insert_after_heading, "
        "insert_after_line, insert_before_line, replace_block, or replace_exact_text."
    )


def _suggested_resolution_for_field(field: str) -> str:
    if field.endswith(".replacement"):
        return "For replace_exact_text or replace_block, provide a non-empty string field named replacement."
    if field.endswith(".target"):
        return "Provide a non-empty string field named target for replace_exact_text, replace_block, insert_after_heading, insert_after_line, or insert_before_line."
    if field.endswith(".insert"):
        return "Provide a non-empty string field named insert for append_to_file, insert_after_heading, insert_after_line, or insert_before_line."
    if field.endswith(".content"):
        return "Provide a non-empty string field named content when creating a new file or using full_file_rewrite."
    if field == "changes":
        return 'Return a JSON object with a top-level "changes" list.'

    return 'Return a JSON object with a top-level "changes" list and valid file change objects.'


def _build_generation_schema_retry_context(
    *,
    workspace_root: Path,
    target: TestGenerationTarget,
    source_content: str,
    test_content: str | None,
    existing_tests_check: ExistingTestsCheck,
    previous_raw_response: str,
    generation_error: dict,
    force: bool,
) -> str:
    prompt_context = build_test_generation_context(
        workspace_root=workspace_root,
        target=target,
        source_content=source_content,
        test_content=test_content,
        existing_tests_check=existing_tests_check,
        force=force,
    )
    allowed_operations = "\n".join(f"- {operation}" for operation in sorted(ALLOWED_OPERATION_BASED_EDIT_OPERATIONS))
    return f"""{prompt_context}

Previous raw response:
{previous_raw_response}

Structured error:
{json.dumps(generation_error, indent=2, ensure_ascii=False)}

Allowed operations:
{allowed_operations}
"""


def _write_generation_error_artifacts(session: ForgeSession, error_payload: dict) -> None:
    write_session_json(session, "test_generation_error.json", error_payload)
    write_session_text(session, "test_generation_error.md", _render_generation_error_markdown(error_payload))


def _render_generation_error_markdown(error_payload: dict) -> str:
    allowed_operations = error_payload.get("allowed_operations", [])
    allowed_lines = "\n".join(f"- {operation}" for operation in allowed_operations) or "- none"
    return f"""# Test Generation Error

- status: {error_payload.get("status", "failed")}
- error_type: {error_payload.get("error_type", "unknown")}
- message: {error_payload.get("message", "unknown")}
- operation: {error_payload.get("operation", "n/a")}
- field: {error_payload.get("field", "n/a")}
- suggested_resolution: {error_payload.get("suggested_resolution", "n/a")}
- raw_response_path: {error_payload.get("raw_response_path", "test_generation_raw_response.json")}

## Allowed operations

{allowed_lines}
"""


def _write_generation_retry_artifacts(
    *,
    session: ForgeSession,
    attempt: int,
    prompt: str,
    raw_response: str,
    metadata: dict,
) -> None:
    if attempt == 1:
        write_session_text(session, "test_generation_schema_retry_prompt.md", prompt)
        write_session_text(session, "test_generation_schema_retry_raw_response.json", raw_response)
        write_session_json(session, "test_generation_schema_retry_metadata.json", metadata)

    prefix = f"test_generation_schema_retry_{attempt}"
    write_session_text(session, f"{prefix}_prompt.md", prompt)
    write_session_text(session, f"{prefix}_raw_response.json", raw_response)
    write_session_json(session, f"{prefix}_metadata.json", metadata)


def _build_generation_failure_result(
    *,
    session: ForgeSession,
    target: TestGenerationTarget,
    prompt_template_ref: str,
    original_symbols: list[str],
    existing_tests_check: ExistingTestsCheck,
    generation_retries: dict,
    generation_error: dict,
    write: bool,
    command_text: str,
    request: TestAddRequest,
) -> TestAddResult:
    metadata = metadata_for_target(
        target=target,
        write=write,
        prompt_ref=prompt_template_ref,
        status="failed_test_generation_schema",
        files_changed=[],
        existing_tests_check=existing_tests_check,
        generation_retries=generation_retries,
        symbols_original=original_symbols,
        provider_called=True,
        write_allowed=False,
    )
    write_session_json(session, "test_generation_metadata.json", metadata)
    write_session_text(
        session,
        "test_generation_summary.md",
        build_test_generation_summary(
            target=target,
            files_changed=[],
            write=write,
            status="failed_test_generation_schema",
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
        ),
    )
    session = update_session_status(session, "tests_add_failed")
    artifacts = [
        "test_generation_error.json",
        "test_generation_error.md",
        "test_generation_raw_response.json",
        "test_generation_metadata.json",
        "test_generation_summary.md",
    ]
    if generation_retries["used"] > 0:
        artifacts.extend(
            [
                "test_generation_schema_retry_prompt.md",
                "test_generation_schema_retry_raw_response.json",
                "test_generation_schema_retry_metadata.json",
            ]
        )
        artifacts.extend(
            [
                "test_generation_schema_retry_1_prompt.md",
                "test_generation_schema_retry_1_raw_response.json",
                "test_generation_schema_retry_1_metadata.json",
            ]
        )
        if generation_retries["used"] > 1:
            for attempt in range(2, generation_retries["used"] + 1):
                artifacts.extend(
                    [
                        f"test_generation_schema_retry_{attempt}_prompt.md",
                        f"test_generation_schema_retry_{attempt}_raw_response.json",
                        f"test_generation_schema_retry_{attempt}_metadata.json",
                    ]
                )
    _record_timeline_event(
        session,
        "tests_add_failed",
        command_text,
        "failed",
        reason="failed_test_generation_schema",
        message=generation_error.get("message"),
        artifacts=artifacts,
    )
    return TestAddResult(
        status="failed_test_generation_schema",
        session_id=session.metadata.id,
        session_path=session.path,
        source_path=target.source_path,
        test_file=target.test_file,
        symbols=original_symbols,
        files_changed=[],
        write_allowed=False,
        applied=False,
        artifacts={
            "error": "test_generation_error.json",
            "error_markdown": "test_generation_error.md",
            "raw_response": "test_generation_raw_response.json",
            "metadata": "test_generation_metadata.json",
            "summary": "test_generation_summary.md",
            **(
                {"generation_retry": "test_generation_schema_retry_metadata.json"}
                if generation_retries["used"] > 0
                else {}
            ),
        },
        message="[red]Generated test file changes failed schema validation.[/red]",
        exit_code=1,
        metadata=metadata,
        prompt_ref=prompt_template_ref,
        next_command=target.suggested_test_command,
    )


def _build_generation_guardrail_failure_result(
    *,
    session: ForgeSession,
    target: TestGenerationTarget,
    prompt_template_ref: str,
    original_symbols: list[str],
    existing_tests_check: ExistingTestsCheck,
    generation_retries: dict,
    guardrail_error: dict,
    write: bool,
    command_text: str,
) -> TestAddResult:
    metadata = metadata_for_target(
        target=target,
        write=write,
        prompt_ref=prompt_template_ref,
        status="failed_test_generation_guardrail",
        files_changed=[],
        existing_tests_check=existing_tests_check,
        generation_retries=generation_retries,
        symbols_original=original_symbols,
        provider_called=True,
        write_allowed=False,
    )
    write_session_json(session, "test_generation_metadata.json", metadata)
    write_session_text(
        session,
        "test_generation_summary.md",
        build_test_generation_summary(
            target=target,
            files_changed=[],
            write=write,
            status="failed_test_generation_guardrail",
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
        ),
    )
    session = update_session_status(session, "tests_add_failed")
    _record_timeline_event(
        session,
        "tests_add_failed",
        command_text,
        "failed",
        reason="failed_test_generation_guardrail",
        message=guardrail_error.get("message"),
        artifacts=[
            "test_generation_validation.json",
            "test_generation_metadata.json",
            "test_generation_summary.md",
        ],
    )
    return TestAddResult(
        status="failed_test_generation_guardrail",
        session_id=session.metadata.id,
        session_path=session.path,
        source_path=target.source_path,
        test_file=target.test_file,
        symbols=original_symbols,
        files_changed=[],
        write_allowed=False,
        applied=False,
        artifacts={
            "validation": "test_generation_validation.json",
            "metadata": "test_generation_metadata.json",
            "summary": "test_generation_summary.md",
        },
        message="[red]Generated test file changes included non-test files.[/red]",
        exit_code=1,
        metadata=metadata,
        prompt_ref=prompt_template_ref,
        next_command=target.suggested_test_command,
    )


def _finalize_sandbox_stage(
    *,
    session: ForgeSession,
    workspace_root: Path,
    target: TestGenerationTarget,
    request: TestAddRequest,
    command_text: str,
    prompt_template_ref: str,
    current_file_changes: FileChangesOutput,
    existing_tests_check: ExistingTestsCheck,
    generation_retries: dict,
    structure_validation: dict,
    unittest_method_repair: dict | None,
    import_repair: dict | None,
    structure_retries: dict,
    original_symbols: list[str],
    sandbox_retries: dict,
) -> dict:
    diff_warnings: list[str] = []
    unified_diff = build_unified_diff_from_file_changes(
        workspace_root=workspace_root,
        file_changes=current_file_changes,
        warnings=diff_warnings,
    )
    write_session_text(session, "test_diff.patch", unified_diff)
    write_session_text(session, "diff.patch", unified_diff)

    validation_result = validate_diff_patch(
        workspace_root=workspace_root,
        session=session,
        diff_text=unified_diff,
    )
    check_patch(workspace_root=workspace_root, session=session)
    validation_payload = validation_result.to_dict()
    validation_payload["git_apply_check"] = "passed"
    validation_payload["test_command"] = target.suggested_test_command
    write_session_json(session, "test_generation_validation.json", validation_payload)
    write_session_json(session, "diff_validation.json", validation_result.to_dict())
    write_session_json(
        session,
        "diff_check.json",
        {"git_apply_check": "passed", "patch_path": str(session.path / "test_diff.patch")},
    )

    test_commands, command_source, symbol_selector = select_test_generation_commands(
        workspace_root=workspace_root,
        target=target,
    )
    command_spec_source = (
        "targeted_test_file"
        if command_source == "targeted"
        else "targeted_symbol"
        if command_source == "targeted_symbol"
        else command_source
    )
    command_specs = [CommandSpec(command=command, source=command_spec_source) for command in test_commands]
    _record_timeline_event(
        session,
        "tests_add_sandbox_started",
        command_text,
        "started",
        test_commands=test_commands,
        command_source=command_source,
        symbol_selector=symbol_selector,
        keep_sandbox=request.keep_sandbox,
    )
    sandbox_result = run_test_specs_in_sandbox(
        repo_root=workspace_root,
        patch_path=session.path / "test_diff.patch",
        command_specs=command_specs,
        timeout_seconds=request.timeout,
        keep_sandbox=request.keep_sandbox,
    )
    write_test_artifacts(session.path, sandbox_result)
    _write_test_sandbox_aliases(
        session.path,
        command_source=command_source,
        symbol_selector=symbol_selector,
    )

    sandbox_metadata = sandbox_result.sandbox or {}
    sandbox_event = "tests_add_sandbox_completed" if sandbox_result.status == "passed" else "tests_add_sandbox_failed"
    _record_timeline_event(
        session,
        sandbox_event,
        command_text,
        "succeeded" if sandbox_result.status == "passed" else "failed",
        reason=None if sandbox_result.status == "passed" else sandbox_result.status,
        artifacts=[
            "test_sandbox_results.json",
            "test_sandbox_output.log",
            "sandbox_test_results.json",
            "sandbox_test_output.log",
        ],
        test_status=sandbox_result.status,
        patch_apply_check=sandbox_metadata.get("patch_apply_check", "unknown"),
        patch_apply=sandbox_metadata.get("patch_apply", "unknown"),
    )

    write_allowed = sandbox_result.status == "passed"
    metadata = metadata_for_target(
        target=target,
        write=request.write,
        prompt_ref=prompt_template_ref,
        status="diff_ready",
        files_changed=[change.path for change in current_file_changes.changes],
        sandbox_status=sandbox_result.status,
        sandbox_commands=test_commands,
        sandbox_command_source=command_source,
        symbol_selector=symbol_selector,
        existing_tests_check=existing_tests_check,
        generation_retries=generation_retries,
        sandbox_retries=sandbox_retries,
        structure_validation=structure_validation,
        unittest_method_repair=unittest_method_repair,
        import_repair=import_repair,
        structure_retries=structure_retries,
        symbols_original=original_symbols,
        provider_called=True,
        write_allowed=write_allowed,
    )
    write_session_json(session, "test_generation_metadata.json", metadata)
    write_session_text(
        session,
        "test_generation_summary.md",
        build_test_generation_summary(
            target=target,
            files_changed=[change.path for change in current_file_changes.changes],
            write=request.write,
            status="diff_ready",
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
            sandbox_retries=sandbox_retries,
            structure_validation=structure_validation,
            unittest_method_repair=unittest_method_repair,
            import_repair=import_repair,
            structure_retries=structure_retries,
        ),
    )

    return {
        "sandbox_result": sandbox_result,
        "metadata": metadata,
        "test_commands": test_commands,
        "command_source": command_source,
        "symbol_selector": symbol_selector,
        "write_allowed": write_allowed,
        "validation_payload": validation_payload,
        "files_changed": [change.path for change in current_file_changes.changes],
        "unified_diff": unified_diff,
    }


def _build_sandbox_retry_context(
    *,
    workspace_root: Path,
    target: TestGenerationTarget,
    source_content: str,
    test_content: str | None,
    existing_tests_check: ExistingTestsCheck,
    current_file_changes: FileChangesOutput,
    sandbox_result,
    sandbox_output: str,
    unified_diff: str,
    force: bool,
) -> str:
    prompt_context = build_test_generation_context(
        workspace_root=workspace_root,
        target=target,
        source_content=source_content,
        test_content=test_content,
        existing_tests_check=existing_tests_check,
        force=force,
    )
    return f"""{prompt_context}

Previous unified diff:
```diff
{unified_diff}
```

Current file_changes:
```json
{json.dumps(current_file_changes.to_dict(), indent=2, ensure_ascii=False)}
```

Sandbox failure:
```json
{json.dumps(sandbox_result.to_dict(), indent=2, ensure_ascii=False)}
```

Sandbox output:
```text
{sandbox_output}
```
"""


def _write_sandbox_retry_artifacts(
    *,
    session: ForgeSession,
    attempt: int,
    prompt: str,
    raw_response: str,
    metadata: dict,
) -> None:
    if attempt == 1:
        write_session_text(session, "test_generation_sandbox_retry_prompt.md", prompt)
        write_session_text(session, "test_generation_sandbox_retry_raw_response.json", raw_response)
        write_session_json(session, "test_generation_sandbox_retry_metadata.json", metadata)

    prefix = f"test_generation_sandbox_retry_{attempt}"
    write_session_text(session, f"{prefix}_prompt.md", prompt)
    write_session_text(session, f"{prefix}_raw_response.json", raw_response)
    write_session_json(session, f"{prefix}_metadata.json", metadata)


def _build_sandbox_failure_result(
    *,
    session: ForgeSession,
    target: TestGenerationTarget,
    prompt_template_ref: str,
    original_symbols: list[str],
    files_changed: list[str],
    existing_tests_check: ExistingTestsCheck,
    generation_retries: dict,
    sandbox_retries: dict,
    unittest_method_repair: dict | None,
    write: bool,
    command_text: str,
    request: TestAddRequest,
    message: str,
) -> TestAddResult:
    metadata = metadata_for_target(
        target=target,
        write=write,
        prompt_ref=prompt_template_ref,
        status="failed_sandbox_after_retries",
        files_changed=files_changed,
        existing_tests_check=existing_tests_check,
        generation_retries=generation_retries,
        sandbox_retries=sandbox_retries,
        unittest_method_repair=unittest_method_repair,
        symbols_original=original_symbols,
        provider_called=True,
        write_allowed=False,
    )
    write_session_json(session, "test_generation_metadata.json", metadata)
    write_session_text(
        session,
        "test_generation_summary.md",
        build_test_generation_summary(
            target=target,
            files_changed=files_changed,
            write=write,
            status="failed_sandbox_after_retries",
            existing_tests_check=existing_tests_check,
            generation_retries=generation_retries,
            sandbox_retries=sandbox_retries,
            unittest_method_repair=unittest_method_repair,
        ),
    )
    session = update_session_status(session, "tests_add_failed")
    _record_timeline_event(
        session,
        "tests_add_failed",
        command_text,
        "failed",
        reason="failed_sandbox_after_retries",
        artifacts=[
            "test_sandbox_results.json",
            "test_sandbox_output.log",
            "test_generation_metadata.json",
            "test_generation_summary.md",
        ],
    )
    return TestAddResult(
        status="failed_sandbox_after_retries",
        session_id=session.metadata.id,
        session_path=session.path,
        source_path=target.source_path,
        test_file=target.test_file,
        symbols=original_symbols,
        files_changed=files_changed,
        write_allowed=False,
        applied=False,
        artifacts={
            "sandbox_results": "test_sandbox_results.json",
            "sandbox_output": "test_sandbox_output.log",
            "metadata": "test_generation_metadata.json",
            "summary": "test_generation_summary.md",
        },
        message=message,
        exit_code=1,
        metadata=metadata,
        prompt_ref=prompt_template_ref,
        next_command=target.suggested_test_command,
    )


def _write_test_sandbox_aliases(
    session_path: Path,
    command_source: str | None = None,
    symbol_selector: dict | None = None,
) -> None:
    aliases = {
        "sandbox_test_results.json": "test_sandbox_results.json",
        "sandbox_test_output.log": "test_sandbox_output.log",
    }

    for source_name, alias_name in aliases.items():
        source_path = session_path / source_name

        if source_path.exists():
            content = source_path.read_text(encoding="utf-8")
            if source_name.endswith(".json") and command_source is not None:
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    payload["command_source"] = command_source
                    if symbol_selector is not None:
                        payload["symbol_selector"] = symbol_selector
                    content = json.dumps(payload, indent=2, ensure_ascii=False)
                    source_path.write_text(content, encoding="utf-8")
            (session_path / alias_name).write_text(content, encoding="utf-8")


def _record_timeline_event(session: ForgeSession, event: str, command: str, status: str, **fields) -> None:
    append_timeline_event(
        session.path,
        {
            "event": event,
            "command": command,
            "status": status,
            "session_id": session.metadata.id,
            **fields,
        },
    )


def _attempt_deterministic_unittest_method_repair(
    *,
    target: TestGenerationTarget,
    file_changes: FileChangesOutput,
    structure_validation: dict,
) -> tuple[FileChangesOutput, dict]:
    if target.framework != "unittest":
        return file_changes, {
            "status": "not_repairable",
            "reason": "framework_not_supported",
            "test_file": target.test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    files = structure_validation.get("files", {})
    nested_paths = [
        path
        for path, result in files.items()
        if any(str(error).startswith("Nested test function `") for error in result.get("errors", []))
    ]

    if not nested_paths:
        return file_changes, {
            "status": "not_repairable",
            "reason": "no_unittest_test_methods",
            "test_file": target.test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    if len(nested_paths) > 1:
        return file_changes, {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": target.test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    path = nested_paths[0]
    path_result = files.get(path, {})
    errors = [str(error) for error in path_result.get("errors", [])]
    non_import_errors = [
        error
        for error in errors
        if not error.startswith("Nested test function `") and not error.startswith("Symbol `")
    ]

    if non_import_errors:
        return file_changes, {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": path,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    path_changes = [change for change in file_changes.changes if change.path == path]
    if not path_changes:
        return file_changes, {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": path,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    if any(change.operation != "append_to_file" for change in path_changes):
        return file_changes, {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": path,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    repaired_path_changes: list[FileChange] = []
    methods_repaired: list[str] = []

    for change in path_changes:
        insert = change.insert
        if not isinstance(insert, str):
            return file_changes, {
                "status": "not_repairable",
                "reason": "complex_nested_structure",
                "test_file": path,
                "strategy": "normalize_unittest_method_indentation",
                "methods_repaired": [],
            }

        repair_result = repair_unittest_method_indentation(content=insert, test_file=path)
        if repair_result["status"] != "repaired":
            return file_changes, repair_result

        methods_repaired.extend(repair_result.get("methods_repaired", []))
        repaired_path_changes.append(
            FileChange(
                path=change.path,
                change_type=change.change_type,
                content=change.content,
                mode=change.mode,
                operation=change.operation,
                target=change.target,
                insert=repair_result["content"],
                replacement=change.replacement,
            )
        )

    repaired_changes: list[FileChange] = []
    queue = list(repaired_path_changes)

    for change in file_changes.changes:
        if change.path != path:
            repaired_changes.append(change)
            continue

        if queue:
            repaired_changes.append(queue.pop(0))
        else:
            repaired_changes.append(change)

    return FileChangesOutput(changes=repaired_changes), {
        "status": "repaired",
        "test_file": path,
        "strategy": "normalize_unittest_method_indentation",
        "methods_repaired": methods_repaired,
    }


def _attempt_deterministic_test_import_repair(
    *,
    workspace_root: Path,
    target: TestGenerationTarget,
    file_changes: FileChangesOutput,
    structure_validation: dict,
) -> tuple[FileChangesOutput, dict]:
    source_symbols = [symbol.name for symbol in target.symbols]
    composed_contents = compose_generated_test_contents(workspace_root=workspace_root, file_changes=file_changes)
    repair_results: list[dict] = []
    repaired_changes: list[FileChange] = []
    changes_by_path: dict[str, list[FileChange]] = {}

    for change in file_changes.changes:
        changes_by_path.setdefault(change.path, []).append(change)

    for path, result in structure_validation.get("files", {}).items():
        errors = result.get("errors", [])
        path_changes = changes_by_path.get(path, [])

        if not errors:
            repaired_changes.extend(path_changes)
            continue

        import_symbols = _extract_missing_import_symbols(errors)

        if len(import_symbols) != len(errors):
            return file_changes, build_test_import_repair_payload(
                test_file=path,
                source_module=target.source_module,
                repair_results=[
                    {
                        "status": "not_repairable",
                        "reason": "non_import_validation_error",
                        "source_module": target.source_module,
                        "symbols": import_symbols,
                        "symbols_added": [],
                    }
                ],
            )

        repair = repair_missing_test_imports(
            content=composed_contents[path],
            test_file=path,
            source_module=target.source_module,
            missing_symbols=import_symbols,
            source_symbols=source_symbols,
        )
        repair_results.append(repair)

        if repair["status"] != "repaired":
            continue

        repair_change = FileChange(**repair["change"])

        if path_changes and path_changes[0].operation == "create_file":
            updated_first = FileChange(
                path=path_changes[0].path,
                change_type=path_changes[0].change_type,
                content=repair["content"],
                mode=path_changes[0].mode,
                operation=path_changes[0].operation,
                target=path_changes[0].target,
                insert=path_changes[0].insert,
                replacement=path_changes[0].replacement,
            )
            repaired_changes.extend([updated_first, *path_changes[1:]])
        else:
            repaired_changes.extend([repair_change, *path_changes])

    if all(result.get("status") == "repaired" for result in repair_results):
        return FileChangesOutput(changes=repaired_changes), build_test_import_repair_payload(
            test_file=next(iter(structure_validation.get("files", {})), target.test_file),
            source_module=target.source_module,
            repair_results=repair_results,
        )

    if not repair_results:
        repair_results = [
            {
                "status": "not_repairable",
                "reason": "no_import_errors_found",
                "source_module": target.source_module,
                "symbols": [],
                "symbols_added": [],
            }
        ]

    return file_changes, build_test_import_repair_payload(
        test_file=next(iter(structure_validation.get("files", {})), target.test_file),
        source_module=target.source_module,
        repair_results=repair_results,
    )


def _summarize_unittest_method_repair(repair_result: dict | None) -> dict | None:
    if repair_result is None:
        return None

    return {
        "status": repair_result.get("status"),
        "test_file": repair_result.get("test_file"),
        "strategy": repair_result.get("strategy"),
        "methods_repaired": repair_result.get("methods_repaired", []),
        "reason": repair_result.get("reason"),
    }


def _extract_missing_import_symbols(errors: list[str]) -> list[str]:
    pattern = re.compile(r"^Symbol `([^`]+)` is used but not imported or defined\.$")
    symbols: list[str] = []

    for error in errors:
        match = pattern.match(error)
        if match:
            symbols.append(match.group(1))

    return sorted(dict.fromkeys(symbols))


def _run_structure_retry_attempt(
    *,
    session: ForgeSession,
    workspace_root: Path,
    target: TestGenerationTarget,
    provider: Provider,
    attempt: int,
    file_changes: FileChangesOutput,
    structure_validation: dict,
    existing_tests_check: ExistingTestsCheck,
    raw_response: str,
    raw_response_parsed: dict,
    import_repair: dict | None,
) -> dict:
    retry_prompt_template = get_prompt("test_generation_retry")
    retry_context = _build_structure_retry_context(
        workspace_root=workspace_root,
        target=target,
        file_changes=file_changes,
        structure_validation=structure_validation,
        raw_response=raw_response,
        raw_response_parsed=raw_response_parsed,
        existing_tests_check=existing_tests_check.to_dict() if existing_tests_check is not None else None,
        import_repair=import_repair,
    )
    prompt = retry_prompt_template.render(test_generation_retry_context=retry_context)
    raw_retry_response = provider.generate(prompt)
    raw_retry_parsed = raw_response_json(raw_retry_response)

    try:
        retry_file_changes = parse_file_changes_output(raw_retry_response)
        validate_file_changes_are_tests_only(retry_file_changes)
    except DiffError as exc:
        metadata = {
            "attempt": attempt,
            "status": "failed",
            "reason": type(exc).__name__,
            "message": str(exc),
        }
        _write_structure_retry_artifacts(
            session=session,
            attempt=attempt,
            prompt=prompt,
            raw_response=raw_retry_response,
            metadata=metadata,
        )
        return {
            "status": "hard_failure",
            "metadata": metadata,
            "prompt": prompt,
            "raw_response": raw_retry_response,
            "raw_response_parsed": raw_retry_parsed,
        }

    retry_structure_validation = validate_file_changes_test_structure(
        workspace_root=workspace_root,
        file_changes=retry_file_changes,
        framework=target.framework,
        source_symbols=[symbol.name for symbol in target.symbols],
    )
    retry_unittest_method_repair: dict | None = None
    retry_import_repair: dict | None = None

    if retry_structure_validation["status"] == "failed":
        repaired_retry_file_changes, retry_unittest_method_repair = _attempt_deterministic_unittest_method_repair(
            target=target,
            file_changes=retry_file_changes,
            structure_validation=retry_structure_validation,
        )
        if retry_unittest_method_repair["status"] == "repaired":
            retry_file_changes = repaired_retry_file_changes
            retry_structure_validation = validate_file_changes_test_structure(
                workspace_root=workspace_root,
                file_changes=retry_file_changes,
                framework=target.framework,
                source_symbols=[symbol.name for symbol in target.symbols],
            )

    if retry_structure_validation["status"] == "failed":
        repaired_retry_file_changes, retry_import_repair = _attempt_deterministic_test_import_repair(
            workspace_root=workspace_root,
            target=target,
            file_changes=retry_file_changes,
            structure_validation=retry_structure_validation,
        )
        if retry_import_repair["status"] == "repaired":
            retry_file_changes = repaired_retry_file_changes
            retry_structure_validation = validate_file_changes_test_structure(
                workspace_root=workspace_root,
                file_changes=retry_file_changes,
                framework=target.framework,
                source_symbols=[symbol.name for symbol in target.symbols],
            )

    metadata = {
        "attempt": attempt,
        "status": retry_structure_validation["status"],
        "source_path": target.source_path,
        "test_file": target.test_file,
        "framework": target.framework,
        "errors": retry_structure_validation.get("errors", []),
        "warnings": retry_structure_validation.get("warnings", []),
        "discovered_tests": retry_structure_validation.get("discovered_tests", []),
        "unittest_method_repair": retry_unittest_method_repair,
        "import_repair": retry_import_repair,
        "file_changes": retry_file_changes.to_dict(),
    }
    _write_structure_retry_artifacts(
        session=session,
        attempt=attempt,
        prompt=prompt,
        raw_response=raw_retry_response,
        metadata=metadata,
    )

    if retry_structure_validation["status"] == "passed":
        return {
            "status": "passed",
            "file_changes": retry_file_changes,
            "structure_validation": retry_structure_validation,
            "import_repair": retry_import_repair,
            "prompt": prompt,
            "raw_response": raw_retry_response,
            "raw_response_parsed": raw_retry_parsed,
            "metadata": metadata,
        }

    return {
        "status": "failed",
        "file_changes": retry_file_changes,
        "structure_validation": retry_structure_validation,
        "import_repair": retry_import_repair,
        "prompt": prompt,
        "raw_response": raw_retry_response,
        "raw_response_parsed": raw_retry_parsed,
        "metadata": metadata,
    }


def _build_structure_retry_context(
    *,
    workspace_root: Path,
    target: TestGenerationTarget,
    file_changes: FileChangesOutput,
    structure_validation: dict,
    raw_response: str,
    raw_response_parsed: dict,
    existing_tests_check: dict | None,
    import_repair: dict | None,
) -> str:
    composed_contents = compose_generated_test_contents(workspace_root=workspace_root, file_changes=file_changes)
    validation_json = json.dumps(structure_validation, indent=2, ensure_ascii=False)
    file_changes_json = json.dumps(file_changes.to_dict(), indent=2, ensure_ascii=False)
    import_repair_json = json.dumps(import_repair, indent=2, ensure_ascii=False) if import_repair is not None else "null"
    existing_tests_json = json.dumps(existing_tests_check, indent=2, ensure_ascii=False) if existing_tests_check is not None else "null"
    current_content = composed_contents.get(target.test_file, "(unavailable)")
    current_response_parsed = json.dumps(raw_response_parsed, indent=2, ensure_ascii=False)
    symbols = "\n".join(f"- {symbol.name}" for symbol in target.symbols) or "- none"
    errors = "\n".join(
        f"- {path}: {error}"
        for path, result in structure_validation.get("files", {}).items()
        for error in result.get("errors", [])
    ) or "- none"

    return f"""Source file: {target.source_path}
Source module: {target.source_module}
Target test file: {target.test_file}
Detected framework: {target.framework}
Mode: {'all_symbols' if target.all_symbols else 'single_symbol'}
Symbols to test:
{symbols}

Existing tests analysis:
{existing_tests_json}

Previous file_changes JSON:
{file_changes_json}

Previous raw response:
{raw_response}

Previous raw response parsed:
{current_response_parsed}

Structure validation:
{validation_json}

Structure validation errors:
{errors}

Import repair:
{import_repair_json}

Current generated test content:
```python
{current_content}
```
"""


def _write_structure_retry_artifacts(
    *,
    session: ForgeSession,
    attempt: int,
    prompt: str,
    raw_response: str,
    metadata: dict,
) -> None:
    prefix = f"test_generation_retry_{attempt}"
    write_session_text(session, f"{prefix}_prompt.md", prompt)
    write_session_text(session, f"{prefix}_raw_response.json", raw_response)
    write_session_json(session, f"{prefix}_metadata.json", metadata)
    if attempt == 1:
        write_session_text(session, "test_generation_retry_prompt.md", prompt)
        write_session_text(session, "test_generation_retry_raw_response.json", raw_response)
        write_session_json(session, "test_generation_retry_metadata.json", metadata)
