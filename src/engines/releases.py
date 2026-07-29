"""Catálogo y descarga de releases oficiales de Ollama."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Never

from nox_agent.errors import ErrorCode, NoxErrorFactory

ProgressHandler = Callable[[int, int | None], None]


@dataclass(frozen=True)
class OllamaRelease:
    version: str
    prerelease: bool
    installer_url: str
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "prerelease": self.prerelease,
            "installer_url": self.installer_url,
            "sha256": self.sha256,
        }


class OllamaReleaseCatalog:
    """Consulta GitHub y valida los instaladores publicados por Ollama."""

    RELEASES_URL = "https://api.github.com/repos/ollama/ollama/releases?per_page=30"
    RELEASE_BY_TAG_URL = "https://api.github.com/repos/ollama/ollama/releases/tags/"
    INSTALLER_NAME = "OllamaSetup.exe"
    USER_AGENT = "Nox-Agent"

    @classmethod
    def releases(cls, *, include_prerelease: bool = False) -> list[OllamaRelease]:
        data = cls._read_json(cls.RELEASES_URL)
        if not isinstance(data, list):
            cls._release_error("La fuente oficial no devolvió una lista de releases.")
        releases: list[OllamaRelease] = []
        for item in data:
            if not isinstance(item, dict) or item.get("draft") is True:
                continue
            prerelease = item.get("prerelease") is True
            if prerelease and not include_prerelease:
                continue
            release = cls._parse_release(item, prerelease=prerelease)
            if release is not None:
                releases.append(release)
        return releases

    @classmethod
    def release(cls, requested: str) -> OllamaRelease:
        releases = cls.releases(include_prerelease=True)
        if requested.casefold() == "latest":
            stable = next((item for item in releases if not item.prerelease), None)
            if stable is not None:
                return stable
        normalized = requested.removeprefix("v").casefold()
        selected = next(
            (item for item in releases if item.version.casefold() == normalized),
            None,
        )
        if selected is not None:
            return selected
        if not normalized or any(character.isspace() for character in normalized):
            cls._release_error(f"Versión solicitada: {requested}")
        data = cls._read_json(f"{cls.RELEASE_BY_TAG_URL}{quote(f'v{normalized}', safe='')}")
        if not isinstance(data, dict):
            cls._release_error(f"Versión solicitada: {requested}")
        selected = cls._parse_release(
            data,
            prerelease=data.get("prerelease") is True,
        )
        if selected is None:
            cls._release_error(f"Versión solicitada: {requested}")
        return selected

    @classmethod
    def download(
        cls,
        release: OllamaRelease,
        destination: Path,
        *,
        on_progress: ProgressHandler | None = None,
    ) -> None:
        request = Request(
            release.installer_url,
            headers={"User-Agent": cls.USER_AGENT},
        )
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with urlopen(request, timeout=60) as response, destination.open("wb") as file:
                raw_length = response.headers.get("Content-Length")
                total = int(raw_length) if raw_length and raw_length.isdigit() else None
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_DOWNLOAD_FAILED,
                detail=f"{release.installer_url} | {error}",
            ) from error
        if digest.hexdigest().casefold() != release.sha256:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_INTEGRITY_FAILED,
                detail=f"Versión: {release.version}",
            )

    @classmethod
    def _parse_release(
        cls,
        data: Mapping[str, object],
        *,
        prerelease: bool,
    ) -> OllamaRelease | None:
        tag = data.get("tag_name")
        assets = data.get("assets")
        if not isinstance(tag, str) or not isinstance(assets, list):
            return None
        asset = next(
            (
                item
                for item in assets
                if isinstance(item, dict)
                and str(item.get("name", "")).casefold()
                == cls.INSTALLER_NAME.casefold()
            ),
            None,
        )
        if not isinstance(asset, dict):
            return None
        url = asset.get("browser_download_url")
        digest = asset.get("digest")
        if not isinstance(url, str) or not isinstance(digest, str):
            return None
        algorithm, separator, checksum = digest.partition(":")
        if algorithm.casefold() != "sha256" or not separator or len(checksum) != 64:
            return None
        return OllamaRelease(
            version=tag.removeprefix("v"),
            prerelease=prerelease,
            installer_url=url,
            sha256=checksum.casefold(),
        )

    @classmethod
    def _read_json(cls, url: str) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": cls.USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_RELEASE_UNAVAILABLE,
                detail=f"{url} | {error}",
            ) from error

    @staticmethod
    def _release_error(detail: str) -> Never:
        raise NoxErrorFactory.create(
            ErrorCode.ENGINE_RELEASE_UNAVAILABLE,
            detail=detail,
        )
