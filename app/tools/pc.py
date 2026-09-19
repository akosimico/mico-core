from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database.database import Database
from app.database.models import AuditLog, PendingActionRecord
from app.tools.base import Tool

AUTO_EXECUTE = "auto_execute"
CONFIRM_REQUIRED = "confirm_required"
PC_TOOL_PERMISSIONS = {
    "open_application": AUTO_EXECUTE,
    "open_project": AUTO_EXECUTE,
    "read_file": AUTO_EXECUTE,
    "search_files": AUTO_EXECUTE,
    "check_git_status": AUTO_EXECUTE,
    "run_command": CONFIRM_REQUIRED,
    "delete_file": CONFIRM_REQUIRED,
    "git_push": CONFIRM_REQUIRED,
    "git_reset": CONFIRM_REQUIRED,
    "deploy": CONFIRM_REQUIRED,
}


def permission_level(tool_name: str) -> str:
    """Return the enforced execution policy for a PC-agent tool."""
    try:
        return PC_TOOL_PERMISSIONS[tool_name]
    except KeyError as exc:
        raise ValueError(f"Unknown PC tool: {tool_name}") from exc


class PCActionService:
    """Local PC actions constrained to the configured workspace and audited."""

    def __init__(self, db: Database, workspace_root: str = ".", allowed_applications: str = ""):
        self.db = db
        self.workspace_root = Path(workspace_root).resolve()
        self.allowed_applications = {item.strip() for item in allowed_applications.split(",") if item.strip()}

    def _path(self, value: str) -> Path:
        candidate = (self.workspace_root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        if candidate != self.workspace_root and self.workspace_root not in candidate.parents:
            raise ValueError("Path must stay inside the configured PC workspace.")
        return candidate

    async def _audit(self, user_id: str | None, action: str, details: dict[str, Any], status: str) -> None:
        async with self.db.session() as session:
            session.add(AuditLog(user_id=user_id, action=action, details=details, status=status))

    async def read_file(self, user_id: str, path: str) -> str:
        target = self._path(path)
        if not target.is_file():
            await self._audit(user_id, "read_file", {"path": path}, "FAILED")
            return "Error: File was not found."
        try:
            content = target.read_text(encoding="utf-8", errors="replace")[:50000]
            await self._audit(user_id, "read_file", {"path": str(target)}, "SUCCESS")
            return content
        except OSError as exc:
            await self._audit(user_id, "read_file", {"path": str(target), "error": str(exc)}, "FAILED")
            return f"Error reading file: {exc}"

    async def search_files(self, user_id: str, query: str, path: str = ".") -> str:
        root = self._path(path)
        if not root.is_dir():
            return "Error: Search path was not found."
        matches: list[str] = []
        needle = query.lower()
        for item in root.rglob("*"):
            if len(matches) >= 50:
                break
            if item.is_file() and needle in item.name.lower():
                matches.append(str(item.relative_to(self.workspace_root)))
        await self._audit(user_id, "search_files", {"query": query, "path": str(root), "matches": len(matches)}, "SUCCESS")
        return "\n".join(matches) if matches else "No matching files found."

    async def check_git_status(self, user_id: str, path: str = ".") -> str:
        root = self._path(path)
        result = await asyncio.to_thread(subprocess.run, ["git", "-C", str(root), "status", "--short"], capture_output=True, text=True, timeout=20)
        status = "SUCCESS" if result.returncode == 0 else "FAILED"
        await self._audit(user_id, "check_git_status", {"path": str(root), "return_code": result.returncode}, status)
        return result.stdout.strip() or ("Working tree clean." if result.returncode == 0 else f"Git error: {result.stderr.strip()}")

    async def open_project(self, user_id: str, path: str = ".") -> str:
        target = self._path(path)
        if not target.is_dir():
            return "Error: Project folder was not found."
        try:
            if hasattr(os, "startfile"):
                await asyncio.to_thread(os.startfile, str(target))  # type: ignore[attr-defined]
            else:
                await asyncio.to_thread(subprocess.Popen, ["xdg-open", str(target)])
            await self._audit(user_id, "open_project", {"path": str(target)}, "SUCCESS")
            return f"Opened project folder `{target}`."
        except OSError as exc:
            await self._audit(user_id, "open_project", {"path": str(target), "error": str(exc)}, "FAILED")
            return f"Error opening project: {exc}"

    async def open_application(self, user_id: str, application: str) -> str:
        if application not in self.allowed_applications:
            await self._audit(user_id, "open_application", {"application": application}, "DENIED")
            return "Error: Application is not in PC_ALLOWED_APPLICATIONS."
        try:
            await asyncio.to_thread(subprocess.Popen, [application])
            await self._audit(user_id, "open_application", {"application": application}, "SUCCESS")
            return f"Opened {application}."
        except OSError as exc:
            await self._audit(user_id, "open_application", {"application": application, "error": str(exc)}, "FAILED")
            return f"Error opening application: {exc}"

    async def request_confirmation(self, user_id: str, action: str, arguments: dict[str, Any]) -> str:
        if permission_level(action) != CONFIRM_REQUIRED:
            raise ValueError("Only confirmation-required actions may be queued.")
        if action == "delete_file":
            target = self._path(str(arguments.get("path", "")))
            if not target.is_file():
                raise ValueError("Only existing files inside the configured PC workspace can be queued for deletion.")
        token = uuid.uuid4().hex[:8].upper()
        async with self.db.session() as session:
            session.add(PendingActionRecord(token=token, user_id=str(user_id), action=action, arguments=arguments, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
        await self._audit(user_id, action, arguments, "PENDING")
        return f"⚠️ Confirmation required for `{action}`. Review the action, then use `!confirm {token}` within 10 minutes."

    async def confirm(self, user_id: str, token: str) -> str:
        token = token.strip().strip("`")
        async with self.db.session() as session:
            pending = (await session.execute(select(PendingActionRecord).where(PendingActionRecord.token == token.upper(), PendingActionRecord.user_id == str(user_id), PendingActionRecord.status == "PENDING"))).scalar_one_or_none()
            if pending is None:
                return "No pending action found for that confirmation code."
            expires = pending.expires_at.replace(tzinfo=timezone.utc) if pending.expires_at.tzinfo is None else pending.expires_at
            if expires < datetime.now(timezone.utc):
                pending.status = "EXPIRED"
                return "That confirmation code has expired."
            pending.status = "CONFIRMED"
            action, arguments = pending.action, dict(pending.arguments)
        try:
            output = await self._execute_confirmed(user_id, action, arguments)
            await self._audit(user_id, action, arguments, "SUCCESS")
            return output
        except Exception as exc:
            await self._audit(user_id, action, {**arguments, "error": str(exc)}, "FAILED")
            return f"Action failed: {exc}"

    async def cancel(self, user_id: str, token: str) -> bool:
        token = token.strip().strip("`")
        async with self.db.session() as session:
            pending = (await session.execute(select(PendingActionRecord).where(PendingActionRecord.token == token.upper(), PendingActionRecord.user_id == str(user_id), PendingActionRecord.status == "PENDING"))).scalar_one_or_none()
            if pending is None:
                return False
            pending.status = "CANCELLED"
            await self._audit(user_id, pending.action, dict(pending.arguments), "CANCELLED")
            return True

    async def _execute_confirmed(self, user_id: str, action: str, args: dict[str, Any]) -> str:
        if action == "delete_file":
            target = self._path(args["path"])
            if not target.is_file():
                raise ValueError("Only existing files inside the workspace may be deleted.")
            await asyncio.to_thread(target.unlink)
            return f"Deleted `{target.name}`."
        if action == "run_command":
            result = await asyncio.create_subprocess_shell(args["command"], cwd=str(self.workspace_root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(result.communicate(), timeout=60)
            return output.decode(errors="replace")[:50000] or f"Command finished with exit code {result.returncode}."
        if action == "git_push":
            result = await asyncio.to_thread(subprocess.run, ["git", "-C", str(self.workspace_root), "push"], capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            return result.stdout.strip() or "Git push completed."
        if action == "git_reset":
            mode = args.get("mode", "--mixed")
            if mode not in {"--soft", "--mixed", "--hard"}:
                raise ValueError("Unsupported git reset mode.")
            result = await asyncio.to_thread(subprocess.run, ["git", "-C", str(self.workspace_root), "reset", mode, args.get("target", "HEAD")], capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            return result.stdout.strip() or f"Git reset {mode} completed."
        if action == "deploy":
            return await self._execute_confirmed(user_id, "run_command", {"command": args["command"]})
        raise ValueError("Unsupported confirmed action.")


def build_pc_tools(service: PCActionService) -> list[Tool]:
    def tool(name: str, description: str, properties: dict[str, Any], required: list[str], func: Any) -> Tool:
        return Tool(name=name, description=description, parameters={"type": "object", "properties": properties, "required": required}, func=func)
    user = {"user_id": {"type": "string", "description": "Discord user ID."}}
    return [
        tool("open_application", "Open an application that is explicitly allowed in PC_ALLOWED_APPLICATIONS.", {**user, "application": {"type": "string"}}, ["user_id", "application"], service.open_application),
        tool("open_project", "Validate and open a project location inside the configured workspace.", {**user, "path": {"type": "string"}}, ["user_id"], service.open_project),
        tool("read_file", "Read a text file inside the configured workspace.", {**user, "path": {"type": "string"}}, ["user_id", "path"], service.read_file),
        tool("search_files", "Search file names inside the configured workspace.", {**user, "query": {"type": "string"}, "path": {"type": "string"}}, ["user_id", "query"], service.search_files),
        tool("check_git_status", "Read the git status of a project in the configured workspace.", {**user, "path": {"type": "string"}}, ["user_id"], service.check_git_status),
        tool("run_command", "Queue a shell command; it never runs until the user confirms it in Discord.", {**user, "command": {"type": "string"}}, ["user_id", "command"], lambda user_id, command: service.request_confirmation(user_id, "run_command", {"command": command})),
        tool("delete_file", "Queue deletion of one workspace file; requires Discord confirmation.", {**user, "path": {"type": "string"}}, ["user_id", "path"], lambda user_id, path: service.request_confirmation(user_id, "delete_file", {"path": path})),
        tool("git_push", "Queue git push; requires Discord confirmation.", user, ["user_id"], lambda user_id: service.request_confirmation(user_id, "git_push", {})),
        tool("git_reset", "Queue git reset; requires Discord confirmation.", {**user, "mode": {"type": "string"}, "target": {"type": "string"}}, ["user_id"], lambda user_id, mode="--mixed", target="HEAD": service.request_confirmation(user_id, "git_reset", {"mode": mode, "target": target})),
        tool("deploy", "Queue a deployment command; requires Discord confirmation.", {**user, "command": {"type": "string"}}, ["user_id", "command"], lambda user_id, command: service.request_confirmation(user_id, "deploy", {"command": command})),
    ]
