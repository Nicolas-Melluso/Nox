"""Menú interactivo para configurar modelos."""

from nox_agent.config.catalog import ConfigScope, ConfigurationCatalog
from nox_agent.config.manager import ConfigurationManager
from nox_agent.tools import ConsoleMenu, MenuItem


class ModelConfigurationMenu:
    def __init__(self, manager: ConfigurationManager, menu: ConsoleMenu) -> None:
        self.manager = manager
        self.menu = menu

    def run(self) -> None:
        while True:
            values = self.manager.effective().values
            selected = self.menu.select(
                "Models",
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
            self._options(ConfigScope(selected.value))

    def _options(self, scope: ConfigScope) -> None:
        while True:
            values = self.manager.effective().values
            selected = self.menu.select(
                "Configuración del modelo",
                [
                    MenuItem(
                        "Proveedor",
                        "models.provider",
                        annotation=values["models.provider"].value,
                    ),
                    MenuItem(
                        "Modelo",
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
        option = ConfigurationCatalog.option("models.provider")
        current = self.manager.effective().values[option.key].value
        items = [
            MenuItem(
                provider,
                provider,
                annotation="Actual" if provider == current else None,
            )
            for provider in option.choices
        ]
        items.append(MenuItem("Volver", "back"))
        selected = self.menu.select("Proveedor", items)
        if selected is None or selected.value == "back":
            return
        self._save({option.key: selected.value}, scope)

    def _text_option(self, key: str, scope: ConfigScope) -> None:
        option = ConfigurationCatalog.option(key)
        current = self.manager.effective().values[key].value
        value = self.menu.input_text(
            option.description,
            option.key,
            current=current,
        )
        if value is None:
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
