"""Coordinación de la preparación de inteligencia usada por Nox."""

from nox_agent.config import ConfigurationManager
from nox_agent.errors import ErrorCode, NoxError, NoxErrorFactory
from nox_agent.models import ProviderFactory, ProviderIntegration
from nox_agent.models.manager import InstalledModel, ModelManager
from nox_agent.models.setup_menu import ModelSetupMenu
from nox_agent.tools import ConsoleMenu


class LocalIntelligenceSetup:
    """Coordina disponibilidad, descarga, selección y persistencia."""

    def __init__(self, manager: ConfigurationManager, menu: ConsoleMenu) -> None:
        self.manager = manager
        self.menu = menu
        self.setup_menu = ModelSetupMenu(menu)

    def ensure_ready(self) -> bool:
        integration = self._integration()
        model_manager = integration.create_manager()
        installed_now = integration.ensure_engine(self.menu)
        if installed_now is None:
            return False

        models = self._available_models(
            integration,
            model_manager,
            wait_first=installed_now,
        )
        if models is None:
            return False
        configured = self.manager.effective().values["models.model"].value
        if model_manager.find(configured, models) is not None:
            return True

        choice = self.setup_menu.choose_model(
            model_manager,
            models,
            configured,
            integration.recommended_model,
        )
        if choice is None:
            return False
        selected = (
            self._download_model(model_manager, choice.name)
            if choice.needs_download
            else choice.name
        )
        scope = self.setup_menu.choose_scope(
            has_project=self.manager.project is not None,
        )
        if scope is None:
            return False

        self.manager.set_many(
            {
                "models.provider": integration.name,
                "models.model": selected,
            },
            scope,
        )
        return True

    def installed_models(self) -> list[InstalledModel] | None:
        integration = self._integration()
        integration.require_engine()
        return self._available_models(
            integration,
            integration.create_manager(),
        )

    def download_interactive(self) -> str | None:
        integration = self._integration()
        model_manager = integration.create_manager()
        installed_now = integration.ensure_engine(self.menu)
        if installed_now is None:
            return None
        models = self._available_models(
            integration,
            model_manager,
            wait_first=installed_now,
        )
        if models is None:
            return None
        name = self.setup_menu.choose_download_name(
            model_manager,
            models,
            integration.recommended_model,
        )
        return self._download_model(model_manager, name) if name else None

    def _available_models(
        self,
        integration: ProviderIntegration,
        model_manager: ModelManager,
        *,
        wait_first: bool = False,
    ) -> list[InstalledModel] | None:
        if wait_first:
            if model_manager.wait_until_available():
                return model_manager.list()
            if integration.recover_service(self.menu, model_manager):
                return model_manager.list()
            return None
        try:
            return model_manager.list()
        except NoxError as error:
            if error.code != ErrorCode.MODEL_PROVIDER_UNAVAILABLE:
                raise
            if integration.recover_service(self.menu, model_manager):
                return model_manager.list()
            return None

    def _download_model(self, model_manager: ModelManager, name: str) -> str:
        existing = model_manager.find(name)
        if existing is not None:
            return existing.name

        self.setup_menu.begin_download(name)
        model_manager.pull(name, on_progress=self.setup_menu.progress)
        self.setup_menu.show_verification()
        installed = model_manager.find(name)
        if installed is None:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_DOWNLOAD_FAILED,
                detail=f"La descarga terminó, pero Nox no encontró {name}.",
            )
        return installed.name

    def _integration(self) -> ProviderIntegration:
        return ProviderFactory.integration(self.manager.effective())
