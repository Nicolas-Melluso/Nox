"""Motores locales administrados por Nox."""

from nox_agent.engines.ollama import OllamaEngine
from nox_agent.engines.releases import OllamaRelease

__all__ = ["OllamaEngine", "OllamaRelease"]
