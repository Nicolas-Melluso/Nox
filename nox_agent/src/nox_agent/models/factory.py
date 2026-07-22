"""Registro explícito de proveedores compatibles con Nox."""

from collections.abc import Callable

from nox_agent.config.manager import EffectiveConfiguration
from nox_agent.errors import ErrorCode, NoxErrorFactory
from nox_agent.models.provider import ModelProvider, ProviderIntegration

IntegrationBuilder = Callable[[EffectiveConfiguration], ProviderIntegration]


def _ollama_integration(
    configuration: EffectiveConfiguration,
) -> ProviderIntegration:
    from nox_agent.models.ollama import OllamaIntegration

    endpoint = configuration.values["models.ollama_url"].value
    return OllamaIntegration(endpoint)


class ProviderFactory:
    """Único registro y punto de construcción de proveedores."""

    _REGISTRY: dict[str, IntegrationBuilder] = {
        "ollama": _ollama_integration,
    }

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(cls._REGISTRY)

    @classmethod
    def integration(
        cls,
        configuration: EffectiveConfiguration,
    ) -> ProviderIntegration:
        provider = configuration.values["models.provider"].value
        builder = cls._REGISTRY.get(provider)
        if builder is None:
            raise NoxErrorFactory.create(
                ErrorCode.CONFIG_VALUE_INVALID,
                detail=f"Proveedor no soportado: {provider}",
            )
        return builder(configuration)

    @classmethod
    def create(cls, configuration: EffectiveConfiguration) -> ModelProvider:
        model = configuration.values["models.model"].value
        if not model:
            raise NoxErrorFactory.create(
                ErrorCode.MODEL_NOT_CONFIGURED,
                detail=(
                    "Descargá uno con `nox models install <nombre>` y "
                    "seleccionalo con `nox models use <nombre> --scope global`."
                ),
            )
        return cls.integration(configuration).create_provider(model)
