"""Estado interno compartido por el CLI y las sesiones de Nox."""

import platform
from collections.abc import Mapping
from pathlib import Path

from nox_agent.config import ConfigurationManager
from nox_agent.context import ProjectContextService
from nox_agent.registry import context_role, load_registry, registry_path

STATUS_SCHEMA_VERSION = 2


class StatusService:
    """Construye una fotografía de Nox sin modificar el sistema."""

    @staticmethod
    def collect(start: Path, *, nox_version: str) -> dict[str, object]:
        manager = ConfigurationManager(start)
        configuration = manager.effective()
        registry = load_registry()
        project = manager.project
        model = configuration.values["models.model"].value
        provider = configuration.values["models.provider"].value
        projects = registry.get("projects")
        project_count = len(projects) if isinstance(projects, dict) else 0
        effective_values = {
            key: value.value for key, value in configuration.values.items()
        }

        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "nox": {
                "name": "Nox",
                "version": nox_version,
                "ready": True,
            },
            "environment": {
                "cwd": str(start.resolve()),
                "os": platform.system(),
                "os_release": platform.release(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
            },
            "project": StatusService._project_status(
                project,
                registry,
                effective_values,
            ),
            "configuration": {
                key: {
                    "value": value.value,
                    "source": value.source,
                }
                for key, value in configuration.values.items()
            },
            "session": {
                "ready": project is not None and bool(model),
                "provider": provider,
                "model": model or None,
            },
            "registry": {
                "path": str(registry_path()),
                "project_count": project_count,
            },
            "capabilities": [
                "project.init",
                "context.read",
                "intent.classify",
                "config.read",
                "config.write",
                "models.configure",
                "models.chat",
                "models.prepare",
                "models.install",
                "models.remove",
                "engines.install",
                "engines.versions",
                "status.read",
                "session.start",
            ],
        }

    @staticmethod
    def _project_status(
        project: object,
        registry: dict[str, object],
        configuration: Mapping[str, str],
    ) -> dict[str, object]:
        from nox_agent.project import ProjectContext

        if not isinstance(project, ProjectContext):
            return {"initialized": False}

        role = context_role(project, registry)
        context = ProjectContextService.load(
            project,
            role=role,
            configuration=configuration,
        )
        projects = registry["projects"]
        assert isinstance(projects, dict)
        entry = projects.get(project.manifest.project_id)
        entry_path = entry.get("path") if isinstance(entry, dict) else None
        registered = (
            isinstance(entry_path, str)
            and Path(entry_path).resolve() == project.root
        )
        parent = None
        if project.parent is not None:
            parent = {
                "id": project.parent.manifest.project_id,
                "name": project.parent.manifest.name,
                "root": str(project.parent.root),
            }
        return {
            "initialized": True,
            "id": project.manifest.project_id,
            "name": project.manifest.name,
            "root": str(project.root),
            "role": role.lower(),
            "health": "healthy",
            "registered": registered,
            "parent": parent,
            "context": context.metadata(),
        }
