import json
import logging
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.full_test_reset import (
    RunTracker,
    ProcessCommandLineParseError,
    classify_process_records,
    ensure_no_existing_job,
    parse_command_line,
    supervise,
)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _process(process_id, name, command_line, parent_process_id=1, executable_path=None):
    return {
        "process_id": process_id,
        "parent_process_id": parent_process_id,
        "name": name,
        "executable_path": executable_path or name,
        "command_line": command_line,
    }


def test_run_tracking_files_are_isolated_from_stale_runs(tmp_path):
    logger = logging.getLogger("test.full_test_reset.stale")
    old_run = RunTracker("old-run", tmp_path, pid=1001, started_at="2026-10-30T10:00:00+00:00")
    old_run.start()
    old_run.finish("succeeded", 0)
    old_status = old_run.status_path.read_text(encoding="utf-8")

    new_run = RunTracker("new-run", tmp_path, pid=1002, started_at="2026-10-31T10:00:00+00:00")
    exit_code, _ = supervise(new_run, lambda: {"dry_run": True}, logger)

    assert exit_code == 0
    assert old_run.status_path.read_text(encoding="utf-8") == old_status
    assert new_run.status_path != old_run.status_path
    status = _read_json(new_run.status_path)
    assert status["run_id"] == "new-run"
    assert status["pid"] == 1002
    assert status["started_at"] == "2026-10-31T10:00:00+00:00"
    assert status["execution_status"] == "succeeded"
    assert status["exit_code"] == 0
    assert not list(tmp_path.glob("*.tmp"))

    reused_run = RunTracker("old-run", tmp_path, pid=1003)
    reused_exit, _ = supervise(reused_run, lambda: {"should_not_run": True}, logger)
    assert reused_exit == 1
    assert old_run.status_path.read_text(encoding="utf-8") == old_status


def test_startup_failure_is_recorded_as_failed(caplog, tmp_path):
    tracker = RunTracker("startup-failure", tmp_path, pid=2001)
    logger = logging.getLogger("test.full_test_reset.startup")

    def fail_startup():
        tracker.set_stage("startup_imports")
        raise ImportError("controlled startup failure")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        exit_code, result = supervise(tracker, fail_startup, logger)

    assert exit_code == 1
    assert result is None
    status = _read_json(tracker.status_path)
    assert status["execution_status"] == "failed"
    assert status["stage"] == "startup_imports"
    assert status["exit_code"] == 1
    assert status["error_type"] == "ImportError"
    assert "Traceback (most recent call last)" in caplog.text
    assert _read_json(tracker.exit_code_path)["exit_code"] == 1


def test_successful_execution_records_exit_code_and_status(tmp_path):
    tracker = RunTracker("successful-run", tmp_path, pid=3001)
    logger = logging.getLogger("test.full_test_reset.success")

    exit_code, result = supervise(tracker, lambda: {"appointments": 20000}, logger)

    assert exit_code == 0
    assert result == {"appointments": 20000}
    for path in (tracker.pid_path, tracker.status_path, tracker.exit_code_path):
        record = _read_json(path)
        assert record["run_id"] == "successful-run"
        assert record["pid"] == 3001
        assert record["execution_status"] == "succeeded"
        assert record["exit_code"] == 0
        assert record["finished_at"]


def test_failed_generation_records_failure_and_exit_code(tmp_path):
    tracker = RunTracker("failed-generation", tmp_path, pid=4001)
    logger = logging.getLogger("test.full_test_reset.generation")

    def fail_generation():
        tracker.set_stage("full_generation")
        raise RuntimeError("controlled generation failure")

    exit_code, result = supervise(tracker, fail_generation, logger)

    assert exit_code == 1
    assert result is None
    status = _read_json(tracker.status_path)
    assert status["run_id"] == "failed-generation"
    assert status["execution_status"] == "failed"
    assert status["stage"] == "full_generation"
    assert status["error_type"] == "RuntimeError"
    assert _read_json(tracker.exit_code_path)["exit_code"] == 1


def test_process_guard_ignores_its_own_supervisor_command():
    own_pid = 5151
    process_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps([{
            "process_id": own_pid,
            "parent_process_id": 1,
            "name": "python.exe",
            "executable_path": r"C:\Python\python.exe",
            "command_line": "python.exe -u -m scripts.full_test_reset --execute",
        }]),
    )
    with patch("scripts.full_test_reset.os.getpid", return_value=own_pid), patch(
        "scripts.full_test_reset.subprocess.run", return_value=process_result
    ):
        ensure_no_existing_job()


def test_process_guard_rejects_another_generator_process():
    process_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps([{
            "process_id": 6161,
            "parent_process_id": 1,
            "name": "python.exe",
            "executable_path": r"C:\Python\python.exe",
            "command_line": "python.exe -u -m generator.generate --mode full",
        }]),
    )
    with patch("scripts.full_test_reset.os.getpid", return_value=5151), patch(
        "scripts.full_test_reset.subprocess.run", return_value=process_result
    ), pytest.raises(RuntimeError, match="another generator or reset process"):
        ensure_no_existing_job()


@pytest.mark.parametrize("failure", ["nonzero_exit", "malformed_json", "timeout"])
def test_process_guard_fails_closed_when_process_query_fails(failure):
    if failure == "timeout":
        result = subprocess.TimeoutExpired("powershell.exe", 15)
        patcher = patch("scripts.full_test_reset.subprocess.run", side_effect=result)
    elif failure == "nonzero_exit":
        result = SimpleNamespace(returncode=1, stdout="", stderr="query failure")
        patcher = patch("scripts.full_test_reset.subprocess.run", return_value=result)
    else:
        result = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
        patcher = patch("scripts.full_test_reset.subprocess.run", return_value=result)

    with patcher, pytest.raises(RuntimeError, match="could not verify|could not parse"):
        ensure_no_existing_job()


def test_process_guard_ignores_powershell_wrapper_mentioning_workflow():
    processes = [_process(
        7171,
        "powershell.exe",
        'powershell.exe -Command "python.exe -m scripts.full_test_reset --execute"',
        executable_path=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )]
    result = classify_process_records(processes, current_pid=5151)

    assert result[0]["accepted_as_competitor"] is False
    assert result[0]["reason"] == "non_python_wrapper_mentions_job_name"
    assert result[0]["command_line_match"] == "scripts.full_test_reset"
    with patch("scripts.full_test_reset.subprocess.run", return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps(processes), stderr=""
    )), patch("scripts.full_test_reset.os.getpid", return_value=5151):
        ensure_no_existing_job()


def test_process_guard_ignores_python_command_string_mentioning_workflow():
    process = _process(
        8181,
        "python.exe",
        'python.exe -c "import scripts.full_test_reset; print(1)"',
    )
    result = classify_process_records([process], current_pid=5151)

    assert result[0]["accepted_as_competitor"] is False
    assert result[0]["reason"] == "python_command_string_excluded"
    with patch("scripts.full_test_reset.subprocess.run", return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps([process]), stderr=""
    )), patch("scripts.full_test_reset.os.getpid", return_value=5151):
        ensure_no_existing_job()


def test_process_guard_ignores_read_only_diagnostic_module():
    process = _process(
        8282,
        "python.exe",
        "python.exe -u -m scripts.full_test_reset --diagnose-processes",
    )
    result = classify_process_records([process], current_pid=5151)

    assert result[0]["accepted_as_competitor"] is False
    assert result[0]["reason"] == "read_only_process_diagnostic_excluded"
    with patch("scripts.full_test_reset.subprocess.run", return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps([process]), stderr=""
    )), patch("scripts.full_test_reset.os.getpid", return_value=5151):
        ensure_no_existing_job()


def test_process_guard_ignores_read_only_supervisor_dry_run():
    process = _process(
        8383,
        "python.exe",
        "python.exe -u -m scripts.full_test_reset --run-id dry-run-1",
    )
    result = classify_process_records([process], current_pid=5151)

    assert result[0]["accepted_as_competitor"] is False
    assert result[0]["reason"] == "read_only_supervisor_invocation"


def test_process_guard_detects_competing_direct_reset_script():
    process = _process(
        9191,
        "python.exe",
        r"python.exe -u D:\dock-yard-scheduler\scripts\full_test_reset.py --execute",
    )
    result = classify_process_records([process], current_pid=5151)

    assert result[0]["accepted_as_competitor"] is True
    assert result[0]["reason"] == "competing_python_script_invocation"
    assert result[0]["command_line_match"] == r"script:scripts\full_test_reset.py"
    with patch("scripts.full_test_reset.subprocess.run", return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps([process]), stderr=""
    )), patch("scripts.full_test_reset.os.getpid", return_value=5151), pytest.raises(
        RuntimeError, match="another generator or reset process"
    ):
        ensure_no_existing_job()


def test_process_guard_reports_pid_parent_and_reason_for_self():
    process = _process(
        5151,
        "python.exe",
        "python.exe -u -m scripts.full_test_reset --diagnose-processes",
        parent_process_id=4242,
    )
    result = classify_process_records([process], current_pid=5151)[0]

    assert result["process_id"] == 5151
    assert result["parent_process_id"] == 4242
    assert result["reason"] == "current_supervisor_pid_excluded"
    assert result["command_line_match"] == "scripts.full_test_reset"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows CommandLineToArgvW")
def test_windows_parser_handles_quoted_executable_and_generator_module():
    command_line = r'"C:\Program Files\Python\python.exe" -u -m generator.generate --mode full'
    arguments = parse_command_line(command_line)

    assert arguments == [
        r"C:\Program Files\Python\python.exe",
        "-u",
        "-m",
        "generator.generate",
        "--mode",
        "full",
    ]
    process = _process(9292, "python.exe", command_line, executable_path=arguments[0])
    classified = classify_process_records([process], current_pid=5151)[0]
    assert classified["accepted_as_competitor"] is True
    assert classified["reason"] == "competing_python_module_invocation"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows CommandLineToArgvW")
def test_windows_parser_handles_spaces_and_backslashes_in_reset_script_path():
    command_line = r'"D:\Python Environments\python.exe" -u "D:\Dock Yard Scheduler\scripts\full_test_reset.py" --execute'
    arguments = parse_command_line(command_line)

    assert arguments[0] == r"D:\Python Environments\python.exe"
    assert arguments[1:3] == ["-u", r"D:\Dock Yard Scheduler\scripts\full_test_reset.py"]
    process = _process(9393, "python.exe", command_line, executable_path=arguments[0])
    classified = classify_process_records([process], current_pid=5151)[0]
    assert classified["accepted_as_competitor"] is True
    assert classified["reason"] == "competing_python_script_invocation"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows CommandLineToArgvW")
def test_windows_parser_handles_embedded_quotes_and_python_command_strings():
    command_line = r'python.exe -c "print(\"full_test_reset\")"'
    arguments = parse_command_line(command_line)

    assert arguments == ["python.exe", "-c", 'print("full_test_reset")']
    classified = classify_process_records(
        [_process(9494, "python.exe", command_line)], current_pid=5151
    )[0]
    assert classified["accepted_as_competitor"] is False
    assert classified["reason"] == "python_command_string_excluded"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows CommandLineToArgvW")
def test_windows_parser_handles_the_unmatched_quote_rejected_by_shlex():
    command_line = 'python.exe -c "print(1)'
    arguments = parse_command_line(command_line)

    assert arguments[:2] == ["python.exe", "-c"]
    assert arguments[2] == "print(1)"
    classified = classify_process_records(
        [_process(9595, "python.exe", command_line)], current_pid=5151
    )[0]
    assert classified["accepted_as_competitor"] is False
    assert classified["reason"] == "python_command_string_excluded"


def test_process_guard_logs_sanitized_identity_on_parser_failure(caplog):
    process = _process(
        9696,
        "python.exe",
        "python.exe -m scripts.full_test_reset credential=do-not-log",
        parent_process_id=8686,
        executable_path=r"D:\Python\python.exe",
    )
    process_result = SimpleNamespace(returncode=0, stdout=json.dumps([process]), stderr="")
    logger = logging.getLogger("test.full_test_reset.parse_error")

    with patch("scripts.full_test_reset.subprocess.run", return_value=process_result), patch(
        "scripts.full_test_reset.os.getpid", return_value=5151
    ), patch("scripts.full_test_reset.parse_command_line", side_effect=ValueError("No closing quotation")), caplog.at_level(
        logging.ERROR, logger=logger.name
    ), pytest.raises(RuntimeError, match="could not parse Python process command line"):
        ensure_no_existing_job(logger)

    assert "pid=9696" in caplog.text
    assert "parent_pid=8686" in caplog.text
    assert "name=python.exe" in caplog.text
    assert "executable_name=python.exe" in caplog.text
    assert "classification_reason=malformed_python_command_line" in caplog.text
    assert "parsing_error_type=ValueError" in caplog.text
    assert "do-not-log" not in caplog.text
    assert "No closing quotation" not in caplog.text