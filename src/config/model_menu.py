"""Menú interactivo para preparar y configurar modelos."""

from nox_agent.config.catalog import ConfigScope, ConfigurationCatalog
from nox_agent.config.manager import ConfigurationManager
from nox_agent.errors import NoxError
from nox_agent.models import ProviderFactory
from nox_agent.models.manager import format_model_size
from nox_agent.models.setup import LocalIntelligenceSetup
from nox_agent.tools import ConsoleMenu, MenuItem


class ModelConfigurationMenu:
    def __init__(self, manager: ConfigurationManager, menu: ConsoleMenu) -> None:
        self.manager = manager
        self.menu = menu
        self.setup = LocalIntelligenceSetup(manager, menu)

    def run(self) -> None:
        while True:
            values = self.manager.effective().values
            selected = self.menu.select(
                "Modelos e inteligencia local",
                [
                    MenuItem("Preparar inteligencia local", "prepare"),
                    MenuItem("Modelos instalados", "installed"),
                    MenuItem("Descargar un modelo", "download"),
                    MenuItem("Modelo actual", "actual"),
                    MenuItem("Configuración avanzada", "advanced"),
                    MenuItem("Volver", "back"),
                ],
                description=(
                    f"Proveedor: {values['models.provider'].value} · "
                    f"Modelo: {values['models.model'].value or '(sin definir)'}"
                ),
            )
            if selected is None or selected.value == "back":
                return
            try:
                self._run_action(selected.value)
            except NoxError as error:
                self.menu.message("Nox no pudo completar la operación", _error_lines(error))

    def _run_action(self, action: str) -> None:
        if action == "prepare":
            if self.setup.ensure_ready():
                self._show_actual(title="Inteligencia local preparada")
        elif action == "installed":
            self._show_installed()
        elif action == "download":
            model = self.setup.download_interactive()
            if model is not None:
                self.menu.message("Modelo descargado", [f"Modelo: {model}"])
        elif action == "actual":
            self._show_actual()
        elif action == "advanced":
            self._scope_menu()

    def _show_installed(self) -> None:
        models = self.setup.installed_models()
        if models is None:
            return
        lines = (
            [f"{model.name} · {format_model_size(model.size)}" for model in models]
            if models
            else [
                "Ollama no tiene modelos instalados.",
                "Elegí ‘Descargar un modelo’.",
            ]
        )
        self.menu.message("Modelos instalados", lines)

    def _show_actual(self, *, title: str = "Modelo actual") -> None:
        values = self.manager.effective().values
        model = values["models.model"]
        self.menu.message(
            title,
            [
                f"Proveedor: {values['models.provider'].value}",
                f"Modelo: {model.value or '(sin definir)'}",
                f"Origen: {model.source}",
                f"URL: {values['models.ollama_url'].value}",
            ],
        )

    def _scope_menu(self) -> None:
        while True:
            values = self.manager.effective().values
            selected = self.menu.select(
                "Configuración avanzada",
                [
                    MenuItem("General de Nox", ConfigScope.GLOBAL.value),
                    MenuItem(
                        "Local (.nox)",
                        ConfigScope.LOCAL.value,
                        enabled=self.manager.project is not None,
                        annotation=None if self.manager.project else "Requiere .nox",
                    ),
                    MenuItem("Volver", "back"),
                ],
                description=(
                    f"Proveedor: {values['models.provider'].value} · "
                    f"Modelo: {values['models.model'].value or '(sin definir)'}"
                ),
            )
            if selected is None or selected.value == "back":
                return
            self._advanced_options(ConfigScope(selected.value))

    def _advanced_options(self, scope: ConfigScope) -> None:
        while True:
            values = self.manager.effective().values
            selected = self.menu.select(
                "Opciones avanzadas del modelo",
                [
                    MenuItem(
                        "Proveedor",
                        "models.provider",
                        annotation=values["models.provider"].value,
                    ),
                    MenuItem(
                        "Nombre manual del modelo",
                        "models.model",
                        annotation=values["models.model"].value or "Sin definir",
                    ),
                    MenuItem(
                        "URL de Ollama",
                        "models.ollama_url",
                        annotation=values["models.ollama_url"].value,
                    ),
                    MenuItem("Volver", "back"),
                ],
                description=f"Ámbito: {self._scope_label(scope)}",
            )
            if selected is None or selected.value == "back":
                return
            if selected.value == "models.provider":
                self._provider(scope)
            else:
                self._text_option(selected.value, scope)

    def _provider(self, scope: ConfigScope) -> None:
        key = "models.provider"
        current = self.manager.effective().values[key].value
        items = [
            MenuItem(
                provider,
                provider,
                annotation="Actual" if provider == current else None,
            )
            for provider in ProviderFactory.names()
        ]
        items.append(MenuItem("Volver", "back"))
        selected = self.menu.select("Proveedor", items)
        if selected is None or selected.value == "back":
            return
        self._save({key: selected.value}, scope)

    def _text_option(self, key: str, scope: ConfigScope) -> None:
        option = ConfigurationCatalog.option(key)
        current = self.manager.effective().values[key].value
        value = self.menu.input_text(
            option.description,
            option.key,
            current=current,
        )
        if not value:
            return
        self._save({key: value}, scope)

    def _save(self, changes: dict[str, object], scope: ConfigScope) -> None:
        saved = self.manager.set_many(changes, scope)
        lines = [f"{key} = {value}" for key, value in saved.items()]
        lines.extend(
            [
                f"Ámbito: {self._scope_label(scope)}",
                f"Archivo: {self.manager.path_for_scope(scope)}",
            ]
        )
        self.menu.message("Configuración guardada", lines)

    @staticmethod
    def _scope_label(scope: ConfigScope) -> str:
        return "General de Nox" if scope == ConfigScope.GLOBAL else "Local (.nox)"


def _error_lines(error: NoxError) -> list[str]:
    lines = [f"[{error.code}] {error.message}"]
    if error.detail:
        lines.append(error.detail)
    return lines
