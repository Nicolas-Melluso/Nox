# Nox Installer

## Activar el entorno local

Desde esta carpeta:

```powershell
.\.venv\Scripts\Activate.ps1
```

Luego, para que Python encuentre el paquete `nox_agent` mientras desarrollamos:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

## Probar el comando principal

```powershell
python -B -m nox_agent --version
python -B -m nox_agent --v
python -B -m nox_agent -version
python -B -m nox_agent -v
python -B -m nox_agent --help
```

## Inicializar un proyecto

Desde la raíz del proyecto que querés inicializar:

```powershell
nox init
```

El comando crea `.nox/project.toml`, agrega `/.nox/` al `.gitignore` y
registra el proyecto en `%LOCALAPPDATA%\Nox\state\projects.json`.

Si el proyecto vive dentro de otro proyecto Nox, el hijo declara a su padre y
Nox informa cuál de los dos contextos está activo.

## Salir del entorno

```powershell
deactivate
```
