import argparse
import json
import logging
import ntpath
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DATABASE = "dock_yard_scheduler_full_test"
MAIN_DATABASE = "dock_yard_scheduler"
SEED = 20261022
LOCK_WAIT_SECONDS = 10
LOG_DIR = ROOT / "logs"
APP_LOG = LOG_DIR / "full_generation.log"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
JOB_MODULES = {"generator.generate", "scripts.full_test_reset"}
JOB_SCRIPTS = {"generator\\generate.py", "scripts\\full_test_reset.py"}
PROCESS_NAME_PATTERN = re.compile(r"(?i)^(?:pythonw?\.exe|powershell\.exe|pwsh\.exe)$")
JOB_NAME_PATTERN = re.compile(r"(?i)generator\.generate|scripts(?:[./\\])full_test_reset|(?<![\w.])full_test_reset")


class CredentialRedactingFormatter(logging.Formatter):
    credential_url = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")

    def format(self, record):
        return self.credential_url.sub(r"\1<redacted>@", super().format(record))


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class RunTracker:
    def __init__(self, run_id, tracking_dir=LOG_DIR, pid=None, started_at=None):
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id must contain 1-64 letters, numbers, underscores, or hyphens")
        self.run_id = run_id
        self.tracking_dir = Path(tracking_dir)
        self.pid = os.getpid() if pid is None else pid
        self.started_at = started_at or datetime.now(timezone.utc).isoformat()
        self.status = "starting"
        self.stage = "startup"
        self.exit_code = None
        self.error_type = None
        self.finished_at = None
        self.claim_path = self.tracking_dir / f"full_generation.{run_id}.claim"
        self.pid_path = self.tracking_dir / f"full_generation.{run_id}.pid.json"
        self.status_path = self.tracking_dir / f"full_generation.{run_id}.status.json"
        self.exit_code_path = self.tracking_dir / f"full_generation.{run_id}.exitcode.json"

    def _record(self):
        common = {
            "run_id": self.run_id,
            "pid": self.pid,
            "started_at": self.started_at,
            "execution_status": self.status,
            "stage": self.stage,
            "exit_code": self.exit_code,
            "finished_at": self.finished_at,
        }
        if self.error_type:
            common["error_type"] = self.error_type
        _atomic_write_json(self.pid_path, common)
        _atomic_write_json(self.exit_code_path, common)
        _atomic_write_json(self.status_path, common)

    def start(self):
        self.tracking_dir.mkdir(parents=True, exist_ok=True)
        with self.claim_path.open("x", encoding="ascii") as stream:
            stream.write(f"{self.run_id} {self.pid} {self.started_at}\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._record()

    def set_stage(self, stage):
        self.stage = stage
        self.status = "running"
        self._record()

    def finish(self, status, exit_code, error_type=None):
        self.status = status
        self.exit_code = exit_code
        self.error_type = error_type
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self._record()


def supervise(tracker, action, logger):
    tracking_started = False
    try:
        tracker.start()
        tracking_started = True
        result = action()
    except Exception as error:
        logger.exception(
            "workflow_failed run_id=%s stage=%s",
            tracker.run_id,
            tracker.stage,
        )
        if not logging.getLogger().handlers:
            traceback.print_exc()
        if tracking_started:
            try:
                tracker.finish("failed", 1, type(error).__name__)
            except Exception:
                logger.exception("tracking_failure run_id=%s", tracker.run_id)
        return 1, None
    try:
        tracker.finish("succeeded", 0)
    except Exception as error:
        logger.exception("tracking_failure run_id=%s", tracker.run_id)
        try:
            tracker.finish("failed", 1, type(error).__name__)
        except Exception:
            logger.exception("failed_to_write_terminal_tracking run_id=%s", tracker.run_id)
        return 1, None
    return 0, result


def configure_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = CredentialRedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers = [logging.FileHandler(APP_LOG, encoding="utf-8"), logging.StreamHandler()]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def read_process_records():
    powershell = r"""
$rows = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(?i:pythonw?\.exe|powershell\.exe|pwsh\.exe)$'
} | ForEach-Object {
    [pscustomobject]@{
        process_id = [int]$_.ProcessId
        parent_process_id = [int]$_.ParentProcessId
        name = [string]$_.Name
        executable_path = [string]$_.ExecutablePath
        command_line = [string]$_.CommandLine
    }
})
if ($rows.Count -eq 0) { '[]' } else { ConvertTo-Json -InputObject $rows -Compress }
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", powershell],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("could not verify generator/reset process state") from error
    if result.returncode != 0:
        raise RuntimeError("could not verify generator/reset process state")
    try:
        processes = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("could not parse generator/reset process state") from error
    return processes


def parse_command_line(command_line):
    if os.name != "nt":
        return shlex.split(command_line, posix=True)

    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    command_line_to_argv = shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    argument_count = ctypes.c_int()
    argv = command_line_to_argv(command_line, ctypes.byref(argument_count))
    if not argv:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [argv[index] for index in range(argument_count.value)]
    finally:
        local_free = kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(argv, ctypes.c_void_p))


class ProcessCommandLineParseError(RuntimeError):
    def __init__(self, process, cause):
        self.process_id = process.get("process_id", process.get("ProcessId"))
        self.parent_process_id = process.get("parent_process_id", process.get("ParentProcessId"))
        self.name = process.get("name", process.get("Name"))
        executable = process.get("executable_path", process.get("ExecutablePath")) or self.name or "unknown"
        self.executable_name = ntpath.basename(str(executable))
        self.classification_reason = "malformed_python_command_line"
        self.parsing_error_type = type(cause).__name__
        super().__init__("could not parse Python process command line")


def classify_process_records(processes, current_pid=None):
    if isinstance(processes, dict):
        processes = [processes]
    if not isinstance(processes, list):
        raise RuntimeError("could not parse generator/reset process state")

    current_pid = os.getpid() if current_pid is None else int(current_pid)
    diagnostics = []
    for process in processes:
        if not isinstance(process, dict):
            raise RuntimeError("could not parse generator/reset process state")
        process_id = process.get("process_id", process.get("ProcessId"))
        parent_pid = process.get("parent_process_id", process.get("ParentProcessId"))
        name = process.get("name", process.get("Name"))
        executable = process.get("executable_path", process.get("ExecutablePath"))
        command_line = process.get("command_line", process.get("CommandLine"))
        try:
            process_id = int(process_id)
            parent_pid = int(parent_pid) if parent_pid is not None else None
        except (TypeError, ValueError) as error:
            raise RuntimeError("could not parse generator/reset process state") from error
        if not isinstance(name, str) or not isinstance(command_line, str):
            raise RuntimeError("could not parse generator/reset process state")

        executable_name = ntpath.basename(executable or name).lower()
        python_process = executable_name in {"python.exe", "pythonw.exe"} and name.lower() in {
            "python.exe", "pythonw.exe"
        }
        mention = ",".join(sorted(set(JOB_NAME_PATTERN.findall(command_line)))) or None
        invocation = None
        reason = "not_a_python_process"
        accepted = False

        if process_id == current_pid:
            reason = "current_supervisor_pid_excluded"
        elif not python_process:
            if mention:
                reason = "non_python_wrapper_mentions_job_name"
        else:
            try:
                tokens = parse_command_line(command_line)
            except Exception as error:
                raise ProcessCommandLineParseError(process, error) from error
            index = 1
            while index < len(tokens):
                token = tokens[index]
                option = token.lower()
                if option == "-c":
                    reason = "python_command_string_excluded"
                    break
                if option == "-m":
                    module = tokens[index + 1].strip("\"'") if index + 1 < len(tokens) else ""
                    if module in JOB_MODULES:
                        arguments = {item.lower() for item in tokens[index + 2:]}
                        if module == "scripts.full_test_reset" and "--diagnose-processes" in arguments:
                            invocation = f"diagnostic:{module}"
                            reason = "read_only_process_diagnostic_excluded"
                        elif module == "scripts.full_test_reset" and "--execute" not in arguments:
                            invocation = f"read_only:{module}"
                            reason = "read_only_supervisor_invocation"
                        else:
                            invocation = f"module:{module}"
                            accepted = True
                            reason = "competing_python_module_invocation"
                    else:
                        reason = "different_python_module"
                    break
                if option.startswith("-"):
                    if option in {"-w", "-x", "--check-hash-based-pycs"}:
                        index += 2
                        continue
                    index += 1
                    continue
                script = token.replace("/", "\\").lower().lstrip(".\\")
                matched_script = next((name for name in JOB_SCRIPTS if script == name or script.endswith("\\" + name)), None)
                if matched_script:
                    invocation = f"script:{matched_script}"
                    accepted = True
                    reason = "competing_python_script_invocation"
                else:
                    reason = "different_python_script"
                break
            if invocation is None and reason == "not_a_python_process":
                reason = "unrelated_python_process"

        diagnostics.append({
            "process_id": process_id,
            "parent_process_id": parent_pid,
            "name": name,
            "executable_path": executable or "",
            "command_line_match": invocation or mention or "none",
            "accepted_as_competitor": accepted,
            "reason": reason,
        })
    return diagnostics


def ensure_no_existing_job(logger=None):
    logger = logger or logging.getLogger("full_test_reset.process_guard")
    processes = read_process_records()
    try:
        diagnostics = classify_process_records(processes, os.getpid())
    except ProcessCommandLineParseError as error:
        logger.error(
            "process_guard_parse_error pid=%s parent_pid=%s name=%s executable_name=%s classification_reason=%s parsing_error_type=%s",
            error.process_id,
            error.parent_process_id,
            error.name,
            error.executable_name,
            error.classification_reason,
            error.parsing_error_type,
        )
        raise RuntimeError(str(error)) from error
    logger.info("process_guard_scan current_pid=%s inspected=%s", os.getpid(), len(diagnostics))
    for item in diagnostics:
        logger.info(
            "process_guard_record pid=%s parent_pid=%s name=%s executable=%s match=%s accepted=%s reason=%s",
            item["process_id"],
            item["parent_process_id"],
            item["name"],
            item["executable_path"],
            item["command_line_match"],
            item["accepted_as_competitor"],
            item["reason"],
        )
    competitors = [item for item in diagnostics if item["accepted_as_competitor"]]
    if competitors:
        pids = ",".join(str(item["process_id"]) for item in competitors)
        raise RuntimeError(f"another generator or reset process is already running; pids={pids}")


def diagnose_processes():
    processes = read_process_records()
    return classify_process_records(processes, os.getpid())


def disk_free_gb():
    return shutil.disk_usage("C:/").free / (1024**3)


def load_target_url():
    from dotenv import load_dotenv
    from sqlalchemy.engine import make_url

    load_dotenv(ROOT / ".env")
    configured = os.environ.get("DATABASE_URL")
    if not configured:
        raise RuntimeError("DATABASE_URL is not configured")
    source_url = make_url(configured)
    if source_url.get_backend_name() != "mysql" or source_url.database != MAIN_DATABASE:
        raise RuntimeError("configured URL must identify the expected MySQL main schema")
    target_url = source_url.set(database=TARGET_DATABASE)
    if target_url.database != TARGET_DATABASE or target_url.database == source_url.database:
        raise RuntimeError("target database override failed")
    os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    return target_url


def create_target_app():
    from app import create_app
    from config import Config
    from sqlalchemy.engine import make_url

    class TargetConfig(Config):
        SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]

    app = create_app(TargetConfig)
    if make_url(app.config["SQLALCHEMY_DATABASE_URI"]).database != TARGET_DATABASE:
        raise RuntimeError("Flask app is not pinned to the dedicated target")
    return app


def verify_partial_target(engine, expected_tables):
    from sqlalchemy import inspect, text

    with engine.connect() as connection:
        active = connection.execute(text("SELECT DATABASE()")).scalar_one()
        if active != TARGET_DATABASE:
            raise RuntimeError("active database is not the authorized target")
        existing_tables = set(inspect(connection).get_table_names())
        expected_partial_tables = expected_tables - {"appointment_timelines"}
        if existing_tables != expected_partial_tables:
            raise RuntimeError("target table inventory differs from the verified partial reset state")
        counts = {
            name: connection.execute(text(f"SELECT COUNT(*) FROM `{name}`")).scalar_one()
            for name in ("facilities", "docks", "appointments", "lifecycle_events", "simulation_runs")
        }
        expected_counts = {
            "facilities": 10,
            "docks": 100,
            "appointments": 7000,
            "lifecycle_events": 0,
            "simulation_runs": 0,
        }
        if counts != expected_counts:
            raise RuntimeError("target counts differ from the last verified partial dataset")
        return existing_tables, counts


def reset_target(app, engine, expected_tables, db, logger):
    from sqlalchemy import inspect, text

    with app.app_context():
        db.session.remove()
        db.engine.dispose()

        stage_started = time.perf_counter()
        with engine.connect() as connection:
            connection.exec_driver_sql(f"SET SESSION lock_wait_timeout = {LOCK_WAIT_SECONDS}")
            if connection.execute(text("SELECT DATABASE()")).scalar_one() != TARGET_DATABASE:
                raise RuntimeError("active database changed before table drop")
            existing_tables = set(inspect(connection).get_table_names())
            for table in reversed(db.metadata.sorted_tables):
                table_started = time.perf_counter()
                if table.name not in existing_tables:
                    logger.info("reset_table_skipped operation=drop table=%s reason=not_present", table.name)
                    continue
                logger.info("reset_table_started operation=drop table=%s", table.name)
                try:
                    table.drop(bind=connection, checkfirst=False)
                except Exception:
                    logger.exception("reset_table_failed operation=drop table=%s", table.name)
                    raise
                logger.info(
                    "reset_table_completed operation=drop table=%s elapsed_seconds=%.3f",
                    table.name,
                    time.perf_counter() - table_started,
                )
        logger.info("reset_drop_phase_completed elapsed_seconds=%.3f", time.perf_counter() - stage_started)

        create_started = time.perf_counter()
        with engine.connect() as connection:
            connection.exec_driver_sql(f"SET SESSION lock_wait_timeout = {LOCK_WAIT_SECONDS}")
            if connection.execute(text("SELECT DATABASE()")).scalar_one() != TARGET_DATABASE:
                raise RuntimeError("active database changed before table creation")
            for table in db.metadata.sorted_tables:
                table_started = time.perf_counter()
                logger.info("reset_table_started operation=create table=%s", table.name)
                try:
                    table.create(bind=connection, checkfirst=True)
                except Exception:
                    logger.exception("reset_table_failed operation=create table=%s", table.name)
                    raise
                logger.info(
                    "reset_table_completed operation=create table=%s elapsed_seconds=%.3f",
                    table.name,
                    time.perf_counter() - table_started,
                )
            actual_tables = set(inspect(connection).get_table_names())
            if actual_tables != expected_tables:
                raise RuntimeError("recreated target schema does not match model metadata")
        logger.info("reset_create_phase_completed elapsed_seconds=%.3f", time.perf_counter() - create_started)
        db.session.remove()


def _execute_workflow(args, tracker, logger):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    tracker.set_stage("preflight")
    ensure_no_existing_job()
    free_gb = disk_free_gb()
    if free_gb < 12:
        raise RuntimeError(f"C: free space is below 12 GB ({free_gb:.2f} GB)")
    target_url = load_target_url()
    logger.info(
        "preflight_passed run_id=%s target=%s main_schema_connection=none c_free_gb=%.2f",
        tracker.run_id,
        TARGET_DATABASE,
        free_gb,
    )

    from generator.generate import generate
    from app import db

    app = create_target_app()
    expected_tables = set(db.metadata.tables)
    engine = create_engine(target_url, poolclass=NullPool, pool_pre_ping=True)
    try:
        tracker.set_stage("read_only_target_verification")
        tables, counts = verify_partial_target(engine, expected_tables)
        logger.info(
            "target_verified run_id=%s database=%s tables=%s counts=%s",
            tracker.run_id,
            TARGET_DATABASE,
            len(tables),
            counts,
        )
        if not args.execute:
            logger.info("dry_run_completed run_id=%s", tracker.run_id)
            return {"dry_run": True, "target": TARGET_DATABASE}
        if args.confirm_target != TARGET_DATABASE:
            raise RuntimeError("--confirm-target must exactly match the authorized database")

        tracker.set_stage("pre_reset_final_guard")
        ensure_no_existing_job()
        free_gb = disk_free_gb()
        if free_gb < 12:
            raise RuntimeError(f"C: free space fell below 12 GB ({free_gb:.2f} GB)")
        verify_partial_target(engine, expected_tables)

        tracker.set_stage("reset_target_tables")
        logger.info(
            "reset_started run_id=%s target=%s metadata_lock_wait_timeout_seconds=%s",
            tracker.run_id,
            TARGET_DATABASE,
            LOCK_WAIT_SECONDS,
        )
        reset_target(app, engine, expected_tables, db, logger)
        free_gb = disk_free_gb()
        if free_gb < 12:
            raise RuntimeError(f"C: free space fell below 12 GB after reset ({free_gb:.2f} GB)")

        tracker.set_stage("full_generation")
        logger.info("full_generation_started run_id=%s seed=%s mode=full horizon_days=60", tracker.run_id, SEED)
        result = generate(seed=SEED, mode="full")
        logger.info("full_generation_result run_id=%s result=%s", tracker.run_id, result)
        return result
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safely reset and populate the dedicated full-test MySQL schema.")
    parser.add_argument("--execute", action="store_true", help="perform the reset and generation; default is read-only preflight")
    parser.add_argument("--confirm-target", default="", help="must exactly equal the dedicated target schema")
    parser.add_argument("--run-id", default=None, help="unique identifier used for per-run tracking files")
    parser.add_argument("--diagnose-processes", action="store_true", help="read-only process classification; no database access")
    args = parser.parse_args(argv)
    if args.diagnose_processes:
        try:
            print(json.dumps({"current_pid": os.getpid(), "processes": diagnose_processes()}, indent=2))
            return 0
        except Exception as error:
            print(json.dumps({"current_pid": os.getpid(), "inspection_error": type(error).__name__, "message": str(error)}))
            return 1
    run_id = args.run_id or uuid.uuid4().hex
    if not RUN_ID_PATTERN.fullmatch(run_id):
        parser.error("--run-id must contain 1-64 letters, numbers, underscores, or hyphens")
    tracker = RunTracker(run_id)
    logger = logging.getLogger("full_test_reset")
    started = time.perf_counter()

    def action():
        tracker.set_stage("startup")
        configure_logging()
        logger.info("workflow_started run_id=%s pid=%s", tracker.run_id, tracker.pid)
        return _execute_workflow(args, tracker, logger)

    exit_code, _ = supervise(tracker, action, logger)
    logger.info(
        "workflow_finished run_id=%s exit_code=%s elapsed_seconds=%.3f",
        tracker.run_id,
        exit_code,
        time.perf_counter() - started,
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
        handler.close()
    logging.getLogger().handlers.clear()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())