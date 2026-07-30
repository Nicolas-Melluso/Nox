"""Operaciones de archivos reutilizables de Nox."""

import os
import tempfile
import time
from pathlib import Path

REPLACE_ATTEMPTS = 5
REPLACE_RETRY_SECONDS = 0.01


class FileManager:
    """Agrupa escrituras seguras que deben compartir varios dominios."""

    @staticmethod
    def atomic_write_text(
        path: Path,
        content: str,
        *,
        create_parents: bool = False,
    ) -> None:
        if create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                prefix=f"{path.name}.nox.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            FileManager._replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    # La limpieza nunca debe ocultar el error de escritura.
                    pass

    @staticmethod
    def _replace(source: Path, destination: Path) -> None:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_RETRY_SECONDS * (2**attempt))
