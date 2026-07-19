"""Centro interactivo de configuración de Nox."""

from pathlib import Path

from nox_agent.config.catalog import (
    ConfigScope,
    ConfigSectionStatus,
    ConfigurationCatalog,
)
from nox_agent.config.manager import ConfigurationManager
from nox_agent.logs import LogLevel, NoxLogs
from nox_agent.tools import ConsoleMenu, MenuItem


class ConfigurationMenu:
    """Navega y modifica opciones usando el catálogo de configuración."""

    def __init__(self, start: Path) -> None:
        self.manager = ConfigurationManager(start)
        self.menu = ConsoleMenu()

    def run(self) -> None:
        while True:
            items = [
                MenuItem(
                    label=section.title,
                    value=section.key,
                    enabled=section.status == ConfigSectionStatus.AVAILABLE,
                    annotation=(
                        "Próximamente"
                        if section.status == ConfigSectionStatus.UPCOMING
                        else None
                    ),
                )
                for section in ConfigurationCatalog.SECTIONS
            ]
            items.extend(
                [
                    MenuItem("Ver configuración actual", "actual"),
                    MenuItem("Salir", "exit"),
                ]
            )
            selected = self.menu.select("Configuración de Nox", items)
            if selected is None or selected.value == "exit":
                self.menu.clear()
                return
            if selected.value == "logs":
                self._logs_menu()
            elif selected.value == "actual":
                self._show_actual()

    def _logs_menu(self) -> None:
        while True:
            effective = self.manager.effective().values["logs.level"]
            items = [
                MenuItem("General de Nox", ConfigScope.GLOBAL.value),
                MenuItem(
                    "Local (.nox)",
                    ConfigScope.LOCAL.value,
                    enabled=self.manager.project is not None,
                    annotation=None if self.manager.project else "Requiere .nox",
                ),
                MenuItem("Volver", "back"),
            ]
            selected = self.menu.select(
                "Logs",
                items,
                description=(
                    f"Nivel actual: {effective.value} · Origen: {effective.source}"
                ),
            )
            if selected is None or selected.value == "back":
                return
            self._log_level_menu(ConfigScope(selected.value))

    def _log_level_menu(self, scope: ConfigScope) -> None:
        stored = self.manager.values_for_scope(scope).get("logs.level")
        items = [
            MenuItem(
                label=level.value,
                value=level.value,
                annotation="Actual" if stored == level.value else None,
            )
            for level in LogLevel
        ]
        items.append(MenuItem("Volver", "back"))
        selected = self.menu.select(
            "Nivel de logs",
            items,
            description=f"Ámbito: {self._scope_label(scope)}",
        )
        if selected is None or selected.value == "back":
            return

        value = self.manager.set("logs.level", selected.value, scope)
        NoxLogs.configure(LogLevel(value))
        self.menu.message(
            "Configuración guardada",
            [
                f"logs.level = {value}",
                f"Ámbito: {self._scope_label(scope)}",
                f"Archivo: {self.manager.path_for_scope(scope)}",
            ],
        )

    def _show_actual(self) -> None:
        lines: list[str] = []
        for key, value in self.manager.effective().values.items():
            lines.extend(
                [
                    f"{key} = {value.value}",
                    f"  Origen: {value.source}",
                    f"  General: {value.global_value or '(sin definir)'}",
                    f"  Local: {value.local_value or '(sin definir)'}",
                    "",
                ]
            )
        self.menu.message("Configuración actual", lines)

    @staticmethod
    def _scope_label(scope: ConfigScope) -> str:
        return "General de Nox" if scope == ConfigScope.GLOBAL else "Local (.nox)"
