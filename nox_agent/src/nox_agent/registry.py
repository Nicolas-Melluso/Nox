"""Registro local de los proyectos conocidos por Nox."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.project import ProjectContext
from nox_agent.tools import FileManager

REGISTRY_SCHEMA_VERSION = 1


def register_context(context: ProjectContext) -> dict[str, object]:
    """Registra el contexto completo, desde el padre raíz hasta el hijo activo."""

    chain: list[ProjectContext] = []
    current: ProjectContext | None = context
    while current is not None:
        chain.append(current)
        current = current.parent

    registry = load_registry()
    projects = registry["projects"]
    assert isinstance(projects, dict)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for project_context in reversed(chain):
        parent_id = (
            project_context.parent.manifest.project_id
            if project_context.parent is not None
            else None
        )
        projects[project_context.manifest.project_id] = {
            "path": str(project_context.root),
            "parent_project_id": parent_id,
            "last_seen": now,
        }

    _write_registry(registry)
    return registry


def context_role(context: ProjectContext, registry: dict[str, object]) -> str:
    if context.parent is not None:
        return "HIJO"

    projects = registry.get("projects", {})
    if isinstance(projects, dict):
        for entry in projects.values():
            if (
                isinstance(entry, dict)
                and entry.get("parent_project_id") == context.manifest.project_id
            ):
                return "PADRE"
    return "RAÍZ"


def load_registry() -> dict[str, object]:
    path = registry_path()
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "projects": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_INVALID,
            detail=f"Leer {path}: {error}",
        ) from error

    if not isinstance(data, dict):
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_INVALID,
            detail="La raíz del registro debe ser un objeto JSON.",
        )
    if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_INVALID,
            detail=f"schema_version: {data.get('schema_version')!r}",
        )
    projects = data.get("projects")
    if not isinstance(projects, dict):
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_INVALID,
            detail="projects debe ser un objeto JSON.",
        )

    for project_id, entry in projects.items():
        if not isinstance(project_id, str) or not isinstance(entry, dict):
            raise NoxErrorFactory.create(
                ErrorCode.REGISTRY_INVALID,
                detail=f"Entrada inválida: {project_id!r}",
            )
        if not isinstance(entry.get("path"), str):
            raise NoxErrorFactory.create(
                ErrorCode.REGISTRY_INVALID,
                detail=f"Ruta inválida para el proyecto {project_id}.",
            )
        parent_id = entry.get("parent_project_id")
        if parent_id is not None and not isinstance(parent_id, str):
            raise NoxErrorFactory.create(
                ErrorCode.REGISTRY_INVALID,
                detail=f"Padre inválido para el proyecto {project_id}.",
            )
    return data


def registry_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_WRITE_FAILED,
            detail="Windows no informó la ubicación LOCALAPPDATA.",
        )
    return Path(local_app_data) / "Nox" / "state" / "projects.json"


def _write_registry(registry: dict[str, object]) -> None:
    path = registry_path()
    try:
        FileManager.atomic_write_text(
            path,
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            create_parents=True,
        )
    except OSError as error:
        raise NoxErrorFactory.create(
            ErrorCode.REGISTRY_WRITE_FAILED,
            detail=str(error),
        ) from error
