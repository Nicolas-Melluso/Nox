# Nox Agent

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
nox config models
nox config models --provider ollama --model <modelo> --scope global
nox config models --model <modelo-del-proyecto> --scope local
```

El ámbito `global` se guarda en `%LOCALAPPDATA%\Nox\config.toml`. El ámbito
`local` se guarda en `.nox/config.toml` y prevalece sobre el general.

Para automatizaciones y agentes se puede agregar `--json`:

```powershell
nox --json config actual
nox --json --config logs
```

Por ahora, `Memory` y `Security` aparecen como `Próximamente`.

## Configurar Ollama

Nox usa Ollama como primer proveedor local, pero no lo instala ni administra.
Con Ollama instalado y un modelo descargado, configurá el nombre exacto:

```powershell
ollama list
nox config models --provider ollama --model <modelo> --scope global
```

La API local predeterminada es `http://127.0.0.1:11434`. Si Ollama está en
otra dirección:

```powershell
nox config models --ollama-url http://servidor:11434 --scope global
```

## Iniciar una conversación

Desde un proyecto inicializado con `nox init`:

```powershell
nox start
```

La sesión conserva el historial solamente en memoria. Sus comandos internos
son:

```text
/help     Muestra la ayuda
/status   Muestra el contexto activo
/clear    Limpia la conversación
/exit     Termina Nox
```

Esta primera versión del REPL conversa con el modelo, pero todavía no ejecuta
herramientas ni modifica archivos.

## Salir del entorno

```powershell
deactivate
```
