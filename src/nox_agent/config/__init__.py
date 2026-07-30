"""Dominio de configuración de Nox."""

from nox_agent.config.catalog import (
    ConfigScope,
    ConfigSectionStatus,
    ConfigurationCatalog,
)
from nox_agent.config.manager import ConfigurationManager, EffectiveConfiguration

__all__ = [
    "ConfigScope",
    "ConfigSectionStatus",
    "ConfigurationCatalog",
    "ConfigurationManager",
    "EffectiveConfiguration",
]
