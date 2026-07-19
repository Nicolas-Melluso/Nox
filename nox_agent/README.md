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

## Configurar Nox

Abrir el menú interactivo con flechas, `Enter` y `Escape`:

```powershell
nox --config
```

La sintaxis `nox config` abre el mismo menú. También se puede consultar o
modificar la configuración directamente:

```powershell
nox config list
nox config actual
nox --config logs
nox --config logs --log-level DEBUG --scope global
nox config logs --log-level WARNING --scope local
```

El ámbito `global` se guarda en `%LOCALAPPDATA%\Nox\config.toml`. El ámbito
`local` se guarda en `.nox/config.toml` y prevalece sobre el general.

Para automatizaciones y agentes se puede agregar `--json`:

```powershell
nox --json config actual
nox --json --config logs
```

Por ahora, `Memory`, `Models` y `Security` aparecen como `Próximamente`.

## Salir del entorno

```powershell
deactivate
```
