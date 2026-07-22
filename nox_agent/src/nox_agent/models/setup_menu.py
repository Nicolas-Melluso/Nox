"""Interfaz de selección usada durante la preparación de modelos."""

from __future__ import annotations

from dataclasses import dataclass

from nox_agent.config import ConfigScope
from nox_agent.models.manager import InstalledModel, ModelManager, format_model_size
from nox_agent.tools import ConsoleMenu, MenuItem


@dataclass(frozen=True)
class ModelChoice:
    name: str
    needs_download: bool


class ModelSetupMenu:
    """Presenta opciones sin ejecutar descargas ni escribir configuración."""

    def __init__(self, menu: ConsoleMenu) -> None:
        self.menu = menu

    def choose_model(
        self,
        manager: ModelManager,
        models: list[InstalledModel],
        configured: str,
        recommended: str | None,
    ) -> ModelChoice | None:
        items = [
            MenuItem(
                model.name,
                f"installed:{model.name}",
                annotation=format_model_size(model.size),
            )
            for model in models
        ]
        if configured:
            items.append(
                MenuItem(
                    f"Descargar el modelo configurado: {configured}",
                    f"configured:{configured}",
                    annotation="No está instalado",
                )
            )
        if (
            recommended
            and manager.find(recommended, models) is None
            and not manager.matches(configured, recommended)
        ):
            items.append(
                MenuItem(
                    f"Descargar {recommended}",
                    f"recommended:{recommended}",
                    annotation="Recomendado inicial",
                )
            )
        items.extend(
            [
                MenuItem("Escribir el nombre de otro modelo", "custom"),
                MenuItem("Volver", "back"),
            ]
        )
        description = (
            "Elegí un modelo ya instalado o descargá uno nuevo."
            if models
            else "El proveedor está listo, pero todavía no tiene modelos."
        )
        selected = self.menu.select("Seleccionar modelo", items, description=description)
        if selected is None or selected.value == "back":
            return None
        if selected.value.startswith("installed:"):
            return ModelChoice(
                selected.value.removeprefix("installed:"),
                needs_download=False,
            )
        if selected.value.startswith("configured:"):
            return ModelChoice(
                selected.value.removeprefix("configured:"),
                needs_download=True,
            )
        if selected.value.startswith("recommended:"):
            return ModelChoice(
                selected.value.removeprefix("recommended:"),
                needs_download=True,
            )
        custom = self.input_model_name()
        return ModelChoice(custom, needs_download=True) if custom else None

    def choose_download_name(
        self,
        manager: ModelManager,
        models: list[InstalledModel],
        recommended: str | None,
    ) -> str | None:
        items: list[MenuItem] = []
        recommended_installed = bool(
            recommended and manager.find(recommended, models) is not None
        )
        if recommended and not recommended_installed:
            items.append(
                MenuItem(
                    f"Descargar {recommended}",
                    recommended,
                    annotation="Recomendado inicial",
                )
            )
        items.extend(
            [
                MenuItem("Escribir otro nombre", "custom"),
                MenuItem("Volver", "back"),
            ]
        )
        description = (
            f"{recommended} ya está instalado y no se descargará otra vez."
            if recommended_installed
            else None
        )
        selected = self.menu.select(
            "Descargar un modelo",
            items,
            description=description,
        )
        if selected is None or selected.value == "back":
            return None
        return self.input_model_name() if selected.value == "custom" else selected.value

    def choose_scope(self, *, has_project: bool) -> ConfigScope | None:
        if not has_project:
            return ConfigScope.GLOBAL
        selected = self.menu.select(
            "Guardar selección del modelo",
            [
                MenuItem(
                    "General de Nox",
                    ConfigScope.GLOBAL.value,
                    annotation="Recomendado",
                ),
                MenuItem("Solo este proyecto (.nox)", ConfigScope.LOCAL.value),
                MenuItem("Volver", "back"),
            ],
            description="Podés reutilizar el modelo o personalizarlo por proyecto.",
        )
        if selected is None or selected.value == "back":
            return None
        return ConfigScope(selected.value)

    def input_model_name(self) -> str | None:
        value = self.menu.input_text(
            "Descargar un modelo",
            "Nombre exacto del modelo",
        )
        return value if value else None

    def begin_download(self, name: str) -> None:
        self.menu.clear()
        self.menu.stream.write(f"Descargando {name}\n\n")
        self.menu.stream.flush()

    def show_verification(self) -> None:
        self.menu.stream.write("\nVerificando el modelo...\n")
        self.menu.stream.flush()

    def progress(
        self,
        status: str,
        completed: int | None,
        total: int | None,
    ) -> None:
        if completed is not None and total:
            shown = f"{status}: {min(100, int(completed * 100 / total)):3d}%"
        else:
            shown = status
        self.menu.stream.write(f"\r{shown:<72}")
        self.menu.stream.flush()
