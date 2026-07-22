"""Detección e instalación segura del motor Ollama en Windows."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import msvcrt

from nox_agent.engines.releases import (
    ProgressHandler,
    OllamaRelease,
    OllamaReleaseCatalog,
)
from nox_agent.errors import ErrorCode, NoxErrorFactory

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")
OLLAMA_SUBJECT_SHA256 = "78bd53c40f735a7078a12479aff2dbf821bf5393e510b46ae65712dc6e618231"
OLLAMA_PUBLIC_KEY_SHA256 = "e38f89f866e72813fb995d3cd82176d7fd31bcc721c1b95ad86a3e82bdb87d7a"
EC_PUBLIC_KEY_OID = "1.2.840.10045.2.1"
P256_PARAMETERS_BASE64 = "BggqhkjOPQMBBw=="
CODE_SIGNING_EKU = "1.3.6.1.5.5.7.3.3"


class OllamaEngine:
    """Administra Ollama sin mezclarlo con la conversación del modelo."""

    @staticmethod
    def executable_path() -> Path | None:
        discovered = shutil.which("ollama")
        if discovered:
            return Path(discovered).resolve()
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            expected = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            if expected.is_file():
                return expected
        return None

    @classmethod
    def application_path(cls) -> Path | None:
        executable = cls.executable_path()
        if executable is None:
            return None
        application = executable.parent / "ollama app.exe"
        return application if application.is_file() else None

    @staticmethod
    def is_local_endpoint(base_url: str) -> bool:
        """Indica si la URL requiere una instalación en esta computadora."""

        hostname = urlparse(base_url).hostname
        return hostname is not None and hostname.casefold() in {
            "127.0.0.1",
            "localhost",
            "::1",
        }

    @classmethod
    def start_service(cls, base_url: str) -> dict[str, object]:
        """Inicia la app oficial o, como alternativa, `ollama serve`."""

        if platform.system() != "Windows":
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_UNSUPPORTED_PLATFORM,
                detail="El inicio administrado de Ollama requiere Windows.",
            )
        if not cls.is_local_endpoint(base_url):
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_START_FAILED,
                detail="Nox no inicia procesos locales para un endpoint remoto.",
            )
        executable = cls.executable_path()
        if executable is None:
            raise NoxErrorFactory.create(ErrorCode.ENGINE_NOT_INSTALLED)

        application = cls.application_path()
        command = [str(application)] if application else [str(executable), "serve"]
        log_file = None
        try:
            stdout: int | object = subprocess.DEVNULL
            stderr: int | object = subprocess.DEVNULL
            if application is None:
                log_path = cls._service_log_path()
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = log_path.open("ab")
                stdout = log_file
                stderr = subprocess.STDOUT
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                close_fds=True,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
                env=cls._service_environment(base_url),
            )
        except OSError as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_START_FAILED,
                detail=str(error),
            ) from error
        finally:
            if log_file is not None:
                log_file.close()
        return {
            "engine": "ollama",
            "pid": process.pid,
            "mode": "application" if application else "serve",
            "executable": command[0],
        }

    @classmethod
    @contextmanager
    def start_lock(
        cls,
        base_url: str,
        *,
        timeout_seconds: float = 30,
    ) -> Iterator[None]:
        """Serializa intentos de inicio sin dejar locks huérfanos."""

        lock_path = cls._start_lock_path(base_url)
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a+b")
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
        except OSError as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_START_FAILED,
                detail=f"No se pudo crear el bloqueo de inicio: {error}",
            ) from error
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        try:
            while not acquired:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise NoxErrorFactory.create(
                            ErrorCode.ENGINE_START_FAILED,
                            detail="Otro proceso de Nox sigue intentando iniciar Ollama.",
                        )
                    time.sleep(0.1)
            yield
        finally:
            if acquired:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            lock_file.close()

    @classmethod
    def installed_version(cls) -> str | None:
        executable = cls.executable_path()
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        match = VERSION_PATTERN.search(f"{result.stdout}\n{result.stderr}")
        return match.group(0) if match else None

    @classmethod
    def status(cls) -> dict[str, object]:
        executable = cls.executable_path()
        return {
            "engine": "ollama",
            "installed": executable is not None,
            "version": cls.installed_version(),
            "executable": str(executable) if executable else None,
        }

    @staticmethod
    def releases(*, include_prerelease: bool = False) -> list[OllamaRelease]:
        return OllamaReleaseCatalog.releases(
            include_prerelease=include_prerelease,
        )

    @classmethod
    def install(
        cls,
        requested_version: str,
        *,
        on_progress: ProgressHandler | None = None,
    ) -> dict[str, object]:
        if platform.system() != "Windows":
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_UNSUPPORTED_PLATFORM,
                detail="Esta primera integración de Ollama requiere Windows.",
            )
        release = OllamaReleaseCatalog.release(requested_version)
        with tempfile.TemporaryDirectory(prefix="nox-ollama-") as temporary:
            installer = Path(temporary) / OllamaReleaseCatalog.INSTALLER_NAME
            OllamaReleaseCatalog.download(
                release,
                installer,
                on_progress=on_progress,
            )
            cls._verify_signature(installer)
            try:
                result = subprocess.run([str(installer)], check=False)
            except OSError as error:
                raise NoxErrorFactory.create(
                    ErrorCode.ENGINE_INSTALL_FAILED,
                    detail=str(error),
                ) from error
            if result.returncode != 0:
                raise NoxErrorFactory.create(
                    ErrorCode.ENGINE_INSTALL_FAILED,
                    detail=f"OllamaSetup.exe terminó con código {result.returncode}.",
                )

        status = cls.status()
        if not status["installed"]:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_INSTALL_FAILED,
                detail="El instalador terminó, pero Nox no encontró ollama.exe.",
            )
        return {"requested_version": release.version, **status}

    @classmethod
    def _verify_signature(cls, installer: Path) -> None:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        powershell = (
            Path(system_root)
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        command = """
$signature = Get-AuthenticodeSignature -LiteralPath $env:NOX_OLLAMA_INSTALLER_PATH
$certificate = $signature.SignerCertificate
if ($null -eq $certificate) {
    [pscustomobject]@{ status = [string]$signature.Status } | ConvertTo-Json -Compress
    exit
}
$sha = [System.Security.Cryptography.SHA256]::Create()
$subjectHash = ([BitConverter]::ToString($sha.ComputeHash($certificate.SubjectName.RawData))).Replace('-', '').ToLowerInvariant()
$keyHash = ([BitConverter]::ToString($sha.ComputeHash($certificate.GetPublicKey()))).Replace('-', '').ToLowerInvariant()
$ekuOids = @(
    $certificate.Extensions |
        Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
        ForEach-Object {
            $eku = [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]$_
            $eku.EnhancedKeyUsages | ForEach-Object { $_.Value }
        }
)
[pscustomobject]@{
    status = [string]$signature.Status
    subject = $certificate.Subject
    subject_sha256 = $subjectHash
    public_key_sha256 = $keyHash
    algorithm = $certificate.PublicKey.Oid.Value
    parameters = [Convert]::ToBase64String($certificate.PublicKey.EncodedParameters.RawData)
    eku = $ekuOids
    timestamped = $null -ne $signature.TimeStamperCertificate
} | ConvertTo-Json -Compress
"""
        environment = os.environ.copy()
        for key in list(environment):
            if key.casefold() == "psmodulepath":
                del environment[key]
        environment["NOX_OLLAMA_INSTALLER_PATH"] = str(installer)
        try:
            result = subprocess.run(
                [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_SIGNATURE_INVALID,
                detail=f"No se pudo validar la firma: {error}",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or "PowerShell no devolvió la firma."
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_SIGNATURE_INVALID,
                detail=detail,
            )
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_SIGNATURE_INVALID,
                detail=f"Metadatos de firma inválidos: {error}",
            ) from error
        cls._validate_signature_metadata(metadata)

    @staticmethod
    def _validate_signature_metadata(metadata: object) -> None:
        if not isinstance(metadata, dict) or metadata.get("status") != "Valid":
            status = metadata.get("status") if isinstance(metadata, dict) else None
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_SIGNATURE_INVALID,
                detail=f"Estado Authenticode: {status or 'desconocido'}.",
            )
        eku = metadata.get("eku")
        valid_identity = (
            metadata.get("subject_sha256") == OLLAMA_SUBJECT_SHA256
            and metadata.get("public_key_sha256") == OLLAMA_PUBLIC_KEY_SHA256
            and metadata.get("algorithm") == EC_PUBLIC_KEY_OID
            and metadata.get("parameters") == P256_PARAMETERS_BASE64
            and isinstance(eku, list)
            and CODE_SIGNING_EKU in eku
            and metadata.get("timestamped") is True
        )
        if not valid_identity:
            subject = metadata.get("subject") or "desconocido"
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_SIGNATURE_INVALID,
                detail=(
                    "La firma es válida, pero la identidad o clave del editor "
                    f"Ollama no está reconocida. Firmante: {subject}. "
                    "Actualizá Nox antes de instalar este artefacto."
                ),
            )

    @staticmethod
    def _service_environment(base_url: str) -> dict[str, str]:
        environment = os.environ.copy()
        parsed = urlparse(base_url)
        port = parsed.port or 11434
        hostname = parsed.hostname or "127.0.0.1"
        if port != 11434:
            shown_host = f"[{hostname}]" if ":" in hostname else hostname
            environment["OLLAMA_HOST"] = f"{shown_host}:{port}"
        return environment

    @staticmethod
    def _service_log_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_START_FAILED,
                detail="Windows no informó LOCALAPPDATA para guardar el log.",
            )
        return Path(local_app_data) / "Nox" / "logs" / "ollama-serve.log"

    @staticmethod
    def _start_lock_path(base_url: str) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise NoxErrorFactory.create(
                ErrorCode.ENGINE_START_FAILED,
                detail="Windows no informó LOCALAPPDATA para coordinar el inicio.",
            )
        identifier = sha256(base_url.casefold().encode("utf-8")).hexdigest()[:16]
        return Path(local_app_data) / "Nox" / "state" / f"ollama-{identifier}.lock"
