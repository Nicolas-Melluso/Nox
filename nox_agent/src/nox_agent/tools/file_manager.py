"""Operaciones de archivos reutilizables de Nox."""

import os
from pathlib import Path


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

        temporary_path = path.with_name(f".{path.name}.nox.tmp")
        try:
            temporary_path.write_text(content, encoding="utf-8", newline="")
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
