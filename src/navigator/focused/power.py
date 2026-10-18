"""Windows power guard for an already-running focused crawl (stdlib only)."""
import argparse
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Run timestamps must include a time zone")
    return parsed


def completed_export(report, export, started_at):
    """Require this run's final report and matching, fully written export."""
    if (report.get("started_at") != started_at
            or report.get("stopping_reason") != "frontier_exhausted"
            or report.get("pending_urls") != 0
            or not report.get("finished_at")):
        raise ValueError("Crawl did not finish its frontier; shutdown cancelled")
    if timestamp(report["finished_at"]) < timestamp(started_at):
        raise ValueError("Invalid completion timestamp")
    exported_run = export.get("last_run", {})
    for field in ("started_at", "finished_at", "stopping_reason", "pending_urls", "retained_findings"):
        if exported_run.get(field) != report.get(field):
            raise ValueError("Export does not match the completed run")
    findings = export.get("findings")
    if (not isinstance(findings, list) or not findings
            or export.get("count") != len(findings)
            or report.get("retained_findings") != len(findings)):
        raise ValueError("Export is empty or incomplete; shutdown cancelled")
    return len(findings)


def discover_processes(metadata):
    """Resolve the launcher and Python child, checking the project command line."""
    pid = int(metadata["pid"])
    if pid <= 0:
        raise ValueError("Invalid crawler PID")
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
        f"Where-Object {{ $_.ProcessId -eq {pid} -or $_.ParentProcessId -eq {pid} }} | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    records = json.loads(result.stdout or "[]")
    records = [records] if isinstance(records, dict) else records
    if pid not in {record["ProcessId"] for record in records}:
        raise ValueError("The crawler is not running; refusing to arm shutdown from an old report")
    root = str(Path(metadata["working_directory"]).resolve()).casefold() + os.sep
    for record in records:
        command_line = record.get("CommandLine") or ""
        if root not in command_line.casefold() or not re.search(r"\bnavigator\s+focused-crawl\b", command_line):
            raise ValueError("PID does not belong to this project's focused crawler")
    return [record["ProcessId"] for record in records]


class WindowsPower:
    def __init__(self):
        if os.name != "nt":
            raise OSError("The power guard currently supports Windows only")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        signatures = (
            (self.kernel.SetThreadExecutionState, [wintypes.DWORD], wintypes.DWORD),
            (self.kernel.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel.GetExitCodeProcess, [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.kernel.WaitForSingleObject, [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.kernel.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel.CreateMutexW, [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            (self.kernel.GetCurrentProcess, [], wintypes.HANDLE),
            (self.advapi.OpenProcessToken, [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
            (self.advapi.LookupPrivilegeValueW, [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p], wintypes.BOOL),
            (self.advapi.AdjustTokenPrivileges, [wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
            (self.advapi.InitiateSystemShutdownExW, [wintypes.LPWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
        )
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    @contextmanager
    def exclusive(self, metadata_path):
        digest = hashlib.sha256(str(metadata_path.resolve()).casefold().encode()).hexdigest()[:24]
        handle = self.kernel.CreateMutexW(None, False, "Local\\FocusedCrawlerPower-" + digest)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        try:
            if error == 183:  # ERROR_ALREADY_EXISTS
                raise ValueError("A power guard is already attached to this metadata file")
            yield
        finally:
            self.kernel.CloseHandle(handle)

    @contextmanager
    def keep_awake(self):
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: display may still turn off.
        if not self.kernel.SetThreadExecutionState(0x80000001):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            self.kernel.SetThreadExecutionState(0x80000000)

    @contextmanager
    def process(self, pid):
        handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield handle  # The open handle remains tied to this process, even if its PID is reused.
        finally:
            self.kernel.CloseHandle(handle)

    def exit_code(self, handle):
        result = self.kernel.WaitForSingleObject(handle, 0)
        if result == 258:  # WAIT_TIMEOUT
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def enable_shutdown(self):
        class Luid(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

        class Privileges(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("luid", Luid), ("attributes", wintypes.DWORD)]

        token = wintypes.HANDLE()
        if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x28, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            privileges = Privileges(count=1, attributes=2)
            if not self.advapi.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(privileges.luid)):
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.set_last_error(0)
            ok = self.advapi.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
            error = ctypes.get_last_error()
            if not ok or error:
                raise ctypes.WinError(error)
        finally:
            self.kernel.CloseHandle(token)

    def shutdown(self, delay):
        # Unlike shutdown.exe /t > 0, this explicitly does NOT force applications closed.
        if not self.advapi.InitiateSystemShutdownExW(
            None, "Focused crawler finished. Results are saved. Cancel with: shutdown /a",
            delay, False, False, 0x80000000,  # Planned, other; power off, do not restart.
        ):
            raise ctypes.WinError(ctypes.get_last_error())


def watch(metadata_path, state_path, system, shutdown=False, delay=120, sleep=time.sleep):
    metadata = read_json(metadata_path)
    report = read_json(metadata["report"])
    started_at = report["started_at"]
    if timestamp(started_at) < timestamp(metadata["started_at"]):
        raise ValueError("Run report predates the active process metadata")
    if report.get("stopping_reason") != "running" or report.get("finished_at"):
        raise ValueError("Attach the power guard while the crawler is still running")
    pids = discover_processes(metadata)
    cancel_path = state_path.with_suffix(".cancel")
    state = {"pid": os.getpid(), "crawler_pids": pids, "crawler_started_at": started_at,
             "metadata": str(metadata_path.resolve()), "shutdown_on_complete": shutdown,
             "shutdown_delay_seconds": delay, "cancel_file": str(cancel_path.resolve())}

    def update(status, **fields):
        state.update(status=status, updated_at=datetime.now(timezone.utc).isoformat(), **fields)
        temporary = state_path.with_name(state_path.name + ".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(state_path)
        print(json.dumps(state), flush=True)

    try:
        with ExitStack() as stack:
            handles = [stack.enter_context(system.process(pid)) for pid in pids]
            if shutdown:
                system.enable_shutdown()  # Check permission now, without requesting a shutdown.
            stack.enter_context(system.keep_awake())
            update("keeping_awake")
            while True:
                if cancel_path.exists():
                    update("cancelled")
                    return
                if read_json(metadata_path) != metadata:
                    raise ValueError("Crawler metadata changed; reattach the guard to the new run")
                codes = [system.exit_code(handle) for handle in handles]
                if all(code is not None for code in codes):
                    break
                sleep(10)
            if any(code != 0 for code in codes):
                raise ValueError(f"Crawler exited with errors {codes}; shutdown cancelled")
            report = read_json(metadata["report"])
            count = completed_export(report, read_json(metadata["export"]), started_at)
            update("completed", retained_findings=count, finished_at=report["finished_at"])
            if shutdown:
                system.shutdown(delay)
                update("shutdown_scheduled")
                sleep(delay)  # Keep the system awake through the Windows warning/countdown.
    except BaseException as error:
        update("error", error=str(error) or type(error).__name__)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=Path("data/focused-active-process.json"))
    parser.add_argument("--state", type=Path, default=Path("data/focused-power-state.json"))
    parser.add_argument("--shutdown-on-complete", action="store_true")
    parser.add_argument("--shutdown-delay", type=int, default=120, help="Windows warning countdown in seconds (at least 60)")
    args = parser.parse_args()
    if args.shutdown_delay < 60:
        parser.error("shutdown-delay must be at least 60 seconds")
    try:
        system = WindowsPower()
        with system.exclusive(args.metadata):
            watch(args.metadata, args.state, system, args.shutdown_on_complete, args.shutdown_delay)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Power guard stopped: {error}\n")


if __name__ == "__main__":
    main()
