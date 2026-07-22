"""Preparación guiada previa a una sesión conversacional."""

from pathlib import Path

from nox_agent.config import ConfigurationManager, EffectiveConfiguration
from nox_agent.models.setup import LocalIntelligenceSetup
from nox_agent.project import InitResult, initialize_project
from nox_agent.registry import context_role, register_context
from nox_agent.tools import ConsoleMenu, MenuItem


class SessionStartup:
    """Prepara proyecto, motor y modelo antes de abrir el REPL."""

    def __init__(
        self,
        start: Path,
        *,
        nox_version: str,
        menu: ConsoleMenu,
    ) -> None:
        self.start = start.resolve()
        self.nox_version = nox_version
        self.menu = menu

    def prepare(self) -> EffectiveConfiguration | None:
        manager = ConfigurationManager(self.start)
        initialization: InitResult | None = None
        if manager.project is None:
            initialization = self._initialize_project()
            if initialization is None:
                return None
            manager = ConfigurationManager(self.start)

        assert manager.project is not None
        registry = register_context(manager.project)
        if initialization is not None:
            self._show_initialized(
                initialization,
                role=context_role(manager.project, registry),
            )
        ready = LocalIntelligenceSetup(manager, self.menu).ensure_ready()
        if not ready:
            self._finish(
                "Preparación cancelada. "
                "El proyecto conserva los pasos que ya se completaron."
            )
            return None
        return manager.effective()

    def _initialize_project(self) -> InitResult | None:
        selected = self.menu.select(
            "Este directorio todavía no usa Nox",
            [
                MenuItem("Sí, inicializar este proyecto", "init"),
                MenuItem("Salir sin hacer cambios", "cancel"),
            ],
            description=(
                "Nox creará .nox y actualizará .gitignore en:\n"
                f"{self.start}"
            ),
        )
        if selected is None or selected.value == "cancel":
            self._finish("Inicio cancelado. No se inicializó el proyecto.")
            return None

        return initialize_project(self.start, nox_version=self.nox_version)

    def _show_initialized(self, result: InitResult, *, role: str) -> None:
        self.menu.clear()
        self.menu.stream.write(
            "Proyecto inicializado correctamente.\n"
            f"Raíz: {result.context.root}\n"
            f"Contexto Nox: {role}\n\n"
        )
        self.menu.stream.flush()

    def _finish(self, message: str) -> None:
        self.menu.clear()
        self.menu.stream.write(f"{message}\n")
        self.menu.stream.flush()
