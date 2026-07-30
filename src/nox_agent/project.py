"""Inicialización, descubrimiento y validación de proyectos Nox."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from nox_agent.context import ProjectContextService
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.tools import FileManager, Validator

NOX_DIRECTORY_NAME = ".nox"
MANIFEST_FILENAME = "project.toml"
GITIGNORE_FILENAME = ".gitignore"
GITIGNORE_ENTRY = "/.nox/"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ParentDeclaration:
    project_id: str
    relative_path: str


@dataclass(frozen=True)
class ProjectManifest:
    schema_version: int
    project_id: str
    name: str
    created_at: str
    created_with: str
    parent: ParentDeclaration | None = None


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    manifest: ProjectManifest
    parent: ProjectContext | None = None


@dataclass(frozen=True)
class InitResult:
    context: ProjectContext
    created: bool
    gitignore_status: str
    context_status: str


def initialize_project(root: Path, *, nox_version: str) -> InitResult:
    """Inicializa o valida el proyecto cuya raíz fue indicada explícitamente."""

    project_root = _resolve_project_root(root)
    nox_directory = project_root / NOX_DIRECTORY_NAME

    if nox_directory.exists():
        if not nox_directory.is_dir():
            raise NoxErrorFactory.create(
                ErrorCode.INVALID_NOX_DIRECTORY,
                detail=f"Ruta: {nox_directory} | Se esperaba una carpeta.",
            )
        context = validate_project(project_root)
        gitignore_status = ensure_gitignore(project_root)
        context_status = ProjectContextService.ensure_file(project_root)
        return InitResult(context, False, gitignore_status, context_status)

    parent_context = find_nearest_parent(project_root)
    gitignore_status = ensure_gitignore(project_root)
    manifest = _new_manifest(
        project_root,
        nox_version=nox_version,
        parent_context=parent_context,
    )
    manifest_content = _render_manifest(manifest)

    created_nox_directory = False
    try:
        nox_directory.mkdir()
        created_nox_directory = True
        FileManager.atomic_write_text(
            nox_directory / MANIFEST_FILENAME,
            manifest_content,
        )
    except OSError as error:
        cleanup_detail = ""
        if created_nox_directory:
            try:
                nox_directory.rmdir()
            except OSError as cleanup_error:
                cleanup_detail = (
                    " | No se pudo retirar la carpeta .nox incompleta: "
                    f"{cleanup_error}"
                )
        raise NoxErrorFactory.create(
            ErrorCode.FILESYSTEM_ERROR,
            detail=(
                f"Crear la configuración del proyecto: {error}"
                f"{cleanup_detail}"
            ),
        ) from error

    context = validate_project(project_root)
    context_status = ProjectContextService.ensure_file(project_root)
    return InitResult(context, True, gitignore_status, context_status)


def _resolve_project_root(root: Path) -> Path:
    try:
        project_root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise NoxErrorFactory.create(
            ErrorCode.PROJECT_ROOT_INVALID,
            detail=f"La ruta dejó de existir: {root}.",
        ) from error
    except OSError as error:
        raise NoxErrorFactory.create(
            ErrorCode.PROJECT_ROOT_INVALID,
            detail=f"No se pudo acceder a {root}: {error}",
        ) from error

    if not project_root.is_dir():
        raise NoxErrorFactory.create(
            ErrorCode.PROJECT_ROOT_INVALID,
            detail=f"Se esperaba una carpeta: {project_root}.",
        )
    return project_root


def validate_project(root: Path) -> ProjectContext:
    """Carga un proyecto y valida recursivamente su relación con el padre."""

    project_root = root.resolve()
    manifest = load_manifest(project_root)
    actual_parent_root = _find_nox_ancestor(project_root)

    if actual_parent_root is None:
        if manifest.parent is not None:
            raise NoxErrorFactory.create(
                ErrorCode.PARENT_RELATIONSHIP_INVALID,
                detail=f"El padre declarado por {project_root} no existe.",
            )
        return ProjectContext(root=project_root, manifest=manifest)

    parent_context = validate_project(actual_parent_root)
    declaration = manifest.parent
    if declaration is None:
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_DECLARATION_INVALID,
            detail=f"El proyecto hijo {project_root} no declara a su padre.",
        )

    declared_parent = (project_root / declaration.relative_path).resolve()
    if declared_parent != actual_parent_root:
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_RELATIONSHIP_INVALID,
            detail=f"Declarado: {declared_parent} | Encontrado: {actual_parent_root}",
        )

    if declaration.project_id != parent_context.manifest.project_id:
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_RELATIONSHIP_INVALID,
            detail=(
                f"Declarado: {declaration.project_id} | "
                f"Encontrado: {parent_context.manifest.project_id}"
            ),
        )

    return ProjectContext(
        root=project_root,
        manifest=manifest,
        parent=parent_context,
    )


def find_nearest_parent(root: Path) -> ProjectContext | None:
    parent_root = _find_nox_ancestor(root.resolve())
    if parent_root is None:
        return None
    return validate_project(parent_root)


def find_active_project(start: Path) -> ProjectContext | None:
    """Encuentra el proyecto Nox más cercano desde una ubicación."""

    current = start.resolve()
    if current.is_file():
        current = current.parent

    while True:
        if (current / NOX_DIRECTORY_NAME).exists():
            return validate_project(current)
        if current.parent == current:
            return None
        current = current.parent


def load_manifest(root: Path) -> ProjectManifest:
    nox_directory = root / NOX_DIRECTORY_NAME
    manifest_path = nox_directory / MANIFEST_FILENAME

    if not nox_directory.is_dir():
        raise NoxErrorFactory.create(
            ErrorCode.INVALID_NOX_DIRECTORY,
            detail=f"Ruta esperada: {nox_directory}",
        )
    if not manifest_path.is_file():
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_MISSING,
            detail=f"Ruta esperada: {manifest_path}",
        )

    try:
        with manifest_path.open("rb") as manifest_file:
            data = tomllib.load(manifest_file)
    except tomllib.TOMLDecodeError as error:
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_TOML,
            detail=str(error),
        ) from error
    except OSError as error:
        raise NoxErrorFactory.create(
            ErrorCode.FILESYSTEM_ERROR,
            detail=f"Leer {manifest_path}: {error}",
        ) from error

    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_SCHEMA,
            detail=f"Esperada: {SCHEMA_VERSION} | Recibida: {schema_version!r}",
        )

    project_id = data.get("project_id")
    if not Validator.is_uuid(project_id):
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_PROJECT_ID,
            detail=f"Valor recibido: {project_id!r}",
        )

    name = data.get("name")
    if not Validator.is_non_empty_string(name):
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_NAME,
            detail=f"Valor recibido: {name!r}",
        )

    created_at = data.get("created_at")
    if not Validator.is_utc_datetime(created_at):
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_CREATED_AT,
            detail=f"Valor recibido: {created_at!r}",
        )

    created_with = data.get("created_with")
    if not Validator.is_non_empty_string(created_with):
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_SCHEMA,
            detail=f"created_with inválido: {created_with!r}",
        )

    parent = _parse_parent(data.get("parent"))
    allowed_keys = {
        "schema_version",
        "project_id",
        "name",
        "created_at",
        "created_with",
        "parent",
    }
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        raise NoxErrorFactory.create(
            ErrorCode.MANIFEST_INVALID_SCHEMA,
            detail=f"Campos desconocidos: {', '.join(unknown_keys)}",
        )

    return ProjectManifest(
        schema_version=schema_version,
        project_id=str(UUID(project_id)),
        name=name.strip(),
        created_at=created_at,
        created_with=created_with.strip(),
        parent=parent,
    )


def ensure_gitignore(root: Path) -> str:
    """Crea .gitignore si falta o agrega la regla de .nox si es necesaria."""

    gitignore_path = root / GITIGNORE_FILENAME
    if not gitignore_path.exists():
        try:
            FileManager.atomic_write_text(gitignore_path, f"{GITIGNORE_ENTRY}\n")
        except OSError as error:
            raise NoxErrorFactory.create(
                ErrorCode.FILESYSTEM_ERROR,
                detail=f"Crear {gitignore_path}: {error}",
            ) from error
        return "creado"

    if not gitignore_path.is_file():
        raise NoxErrorFactory.create(
            ErrorCode.FILESYSTEM_ERROR,
            detail=f"{gitignore_path} existe, pero no es un archivo.",
        )

    try:
        raw_content = gitignore_path.read_bytes()
        content = raw_content.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise NoxErrorFactory.create(
            ErrorCode.FILESYSTEM_ERROR,
            detail=f"Leer {gitignore_path} como UTF-8: {error}",
        ) from error

    equivalent_entries = {".nox", ".nox/", "/.nox", "/.nox/"}
    active_entries = {
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if active_entries & equivalent_entries:
        return "sin cambios"

    newline = "\r\n" if "\r\n" in content else "\n"
    prefix = "" if not content or content.endswith(("\n", "\r")) else newline
    updated_content = f"{content}{prefix}{GITIGNORE_ENTRY}{newline}"
    try:
        FileManager.atomic_write_text(gitignore_path, updated_content)
    except OSError as error:
        raise NoxErrorFactory.create(
            ErrorCode.FILESYSTEM_ERROR,
            detail=f"Actualizar {gitignore_path}: {error}",
        ) from error
    return "actualizado"


def _new_manifest(
    root: Path,
    *,
    nox_version: str,
    parent_context: ProjectContext | None,
) -> ProjectManifest:
    parent = None
    if parent_context is not None:
        relative_path = os.path.relpath(parent_context.root, start=root)
        parent = ParentDeclaration(
            project_id=parent_context.manifest.project_id,
            relative_path=Path(relative_path).as_posix(),
        )

    return ProjectManifest(
        schema_version=SCHEMA_VERSION,
        project_id=str(uuid4()),
        name=root.name or str(root),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        created_with=nox_version,
        parent=parent,
    )


def _render_manifest(manifest: ProjectManifest) -> str:
    lines = [
        f"schema_version = {manifest.schema_version}",
        f"project_id = {json.dumps(manifest.project_id, ensure_ascii=False)}",
        f"name = {json.dumps(manifest.name, ensure_ascii=False)}",
        f"created_at = {json.dumps(manifest.created_at, ensure_ascii=False)}",
        f"created_with = {json.dumps(manifest.created_with, ensure_ascii=False)}",
    ]
    if manifest.parent is not None:
        lines.extend(
            [
                "",
                "[parent]",
                f"project_id = {json.dumps(manifest.parent.project_id)}",
                f"relative_path = {json.dumps(manifest.parent.relative_path)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _parse_parent(value: object) -> ParentDeclaration | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_DECLARATION_INVALID,
            detail="parent debe ser una tabla TOML.",
        )

    project_id = value.get("project_id")
    relative_path = value.get("relative_path")
    if not Validator.is_uuid(project_id):
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_DECLARATION_INVALID,
            detail=f"parent.project_id inválido: {project_id!r}",
        )
    if not Validator.is_relative_path(relative_path):
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_DECLARATION_INVALID,
            detail=f"parent.relative_path inválido: {relative_path!r}",
        )
    unknown_keys = sorted(set(value) - {"project_id", "relative_path"})
    if unknown_keys:
        raise NoxErrorFactory.create(
            ErrorCode.PARENT_DECLARATION_INVALID,
            detail=f"Campos desconocidos: {', '.join(unknown_keys)}",
        )
    return ParentDeclaration(
        project_id=str(UUID(project_id)),
        relative_path=relative_path.strip(),
    )


def _find_nox_ancestor(root: Path) -> Path | None:
    current = root.parent
    while True:
        if (current / NOX_DIRECTORY_NAME).exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
