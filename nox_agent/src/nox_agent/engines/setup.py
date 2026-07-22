"""Preparación interactiva del motor local Ollama."""

from collections.abc import Callable

from nox_agent.engines.ollama import OllamaEngine
from nox_agent.errors import NoxError
from nox_agent.tools import ConsoleMenu, MenuItem


class OllamaSetup:
    """Instala la versión de Ollama elegida por el usuario."""

    def __init__(self, menu: ConsoleMenu) -> None:
        self.menu = menu

    def ensure(self, base_url: str) -> bool | None:
        """Devuelve si instaló Ollama o None cuando el usuario cancela."""

        if not OllamaEngine.is_local_endpoint(base_url):
            return False
        if OllamaEngine.executable_path() is not None:
            return False

        selected = self.menu.select(
            "Preparar inteligencia local",
            [
                MenuItem("Instalar la última versión de Ollama", "latest"),
                MenuItem("Elegir una versión de Ollama", "version"),
                MenuItem(
                    "Otros proveedores",
                    "other",
                    enabled=False,
                    annotation="Próximamente",
                ),
                MenuItem("Volver", "back"),
            ],
            description=(
                "Nox necesita un motor para ejecutar modelos locales. "
                "La descarga se realiza desde la fuente oficial de Ollama."
            ),
        )
        if selected is None or selected.value == "back":
            return None

        version = "latest"
        if selected.value == "version":
            version = self._choose_version()
            if version is None:
                return None
        self._install(version)
        return True

    def recover_service(
        self,
        base_url: str,
        probe: Callable[[], bool],
        wait_until_available: Callable[[], bool],
    ) -> bool:
        """Ofrece reintentar o iniciar Ollama sin duplicar procesos."""

        can_start = (
            OllamaEngine.is_local_endpoint(base_url)
            and OllamaEngine.executable_path() is not None
        )
        started_in_this_flow = False
        while True:
            items = []
            if can_start and not started_in_this_flow:
                items.append(MenuItem("Iniciar Ollama y reintentar", "start"))
            items.extend(
                [
                    MenuItem("Reintentar conexión", "retry"),
                    MenuItem("Volver", "back"),
                ]
            )
            selected = self.menu.select(
                "Ollama está instalado pero no responde",
                items,
                description=f"Endpoint: {base_url}",
            )
            if selected is None or selected.value == "back":
                return False

            if selected.value == "start":
                try:
                    with OllamaEngine.start_lock(base_url):
                        if probe():
                            return True
                        started = OllamaEngine.start_service(base_url)
                        started_in_this_flow = True
                        self.menu.clear()
                        self.menu.stream.write(
                            "Iniciando Ollama...\n"
                            f"PID: {started['pid']}\n\n"
                        )
                        self.menu.stream.flush()
                        if wait_until_available():
                            return True
                except NoxError as error:
                    self._show_error(error)
                    continue
            elif wait_until_available():
                return True

            self.menu.message(
                "Ollama todavía no responde",
                [
                    f"Endpoint: {base_url}",
                    "Podés reintentar o volver sin continuar al REPL.",
                ],
            )

    def _choose_version(self) -> str | None:
        releases = OllamaEngine.releases()[:10]
        items = [
            MenuItem(
                f"Ollama {release.version}",
                release.version,
                annotation="Más reciente" if index == 0 else None,
            )
            for index, release in enumerate(releases)
        ]
        items.append(MenuItem("Volver", "back"))
        selected = self.menu.select("Versiones oficiales de Ollama", items)
        if selected is None or selected.value == "back":
            return None
        return selected.value

    def _install(self, version: str) -> None:
        self.menu.clear()
        shown = "más reciente" if version == "latest" else version
        self.menu.stream.write(f"Instalando Ollama {shown}\n\n")
        self.menu.stream.flush()
        OllamaEngine.install(version, on_progress=self._progress)
        self.menu.stream.write("\nOllama quedó instalado. Verificando el servicio...\n")
        self.menu.stream.flush()

    def _progress(self, downloaded: int, total: int | None) -> None:
        if total:
            percent = min(100, int(downloaded * 100 / total))
            text = f"\rDescargando Ollama: {percent:3d}%"
        else:
            text = f"\rDescargando Ollama: {downloaded / (1024 * 1024):.1f} MiB"
        self.menu.stream.write(text)
        self.menu.stream.flush()

    def _show_error(self, error: NoxError) -> None:
        lines = [f"[{error.code}] {error.message}"]
        if error.detail:
            lines.append(error.detail)
        self.menu.message("No se pudo iniciar Ollama", lines)
