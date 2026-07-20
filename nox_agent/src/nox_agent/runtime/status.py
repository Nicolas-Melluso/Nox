"""Estado interno compartido por el CLI y las sesiones de Nox."""

import platform
from pathlib import Path

from nox_agent.config import ConfigurationManager
from nox_agent.registry import context_role, load_registry, registry_path

STATUS_SCHEMA_VERSION = 1


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
            "project": StatusService._project_status(project, registry),
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
                "project_count": len(registry["projects"]),
            },
            "capabilities": [
                "project.init",
                "config.read",
                "config.write",
                "models.configure",
                "models.chat",
                "status.read",
                "session.start",
            ],
        }

    @staticmethod
    def _project_status(project: object, registry: dict[str, object]) -> dict[str, object]:
        from nox_agent.project import ProjectContext

        if not isinstance(project, ProjectContext):
            return {"initialized": False}

        projects = registry["projects"]
        assert isinstance(projects, dict)
        entry = projects.get(project.manifest.project_id)
        registered = (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and Path(entry["path"]).resolve() == project.root
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
            "role": context_role(project, registry).lower(),
            "health": "healthy",
            "registered": registered,
            "parent": parent,
        }
