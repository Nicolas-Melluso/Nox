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

Al ejecutar solamente `nox` en una terminal interactiva se abre el inicio
guiado. Desde ahí se puede iniciar Nox, preparar la inteligencia local o abrir
la configuración. `nox --help` conserva la ayuda técnica completa.

Los menús habilitan temporalmente el modo de terminal virtual cuando Windows
lo admite. En consolas sin ese soporte, Nox usa las API de consola de Windows y
no imprime secuencias ANSI como texto.

## Inicializar un proyecto

Desde la raíz del proyecto que querés inicializar:

```powershell
nox init
```

El comando crea `.nox/project.toml`, agrega `/.nox/` al `.gitignore` y
registra el proyecto en `%LOCALAPPDATA%\Nox\state\projects.json`.

Antes de escribir, Nox comprueba que la raíz siga existiendo. Los archivos se
reemplazan mediante un temporal único en el mismo directorio; una raíz que
desaparece nunca se vuelve a crear silenciosamente.

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

## Administrar Ollama

Nox puede detectar Ollama, consultar sus versiones oficiales y abrir su
instalador verificado:

```powershell
nox engines status
nox engines versions ollama
nox engines install ollama
nox engines install ollama --version <version>
```

La instalación siempre pide confirmación. Para una automatización previamente
autorizada se puede agregar `--yes`.

Antes de ejecutar el instalador, Nox valida que la firma Authenticode sea
válida y que coincidan la identidad, la clave pública, el uso de firma de
código y el sello de tiempo del editor oficial de Ollama.

## Administrar modelos

El camino más sencillo es abrir el menú interactivo:

```powershell
nox models
```

Desde ese menú se puede preparar Ollama, ver modelos instalados, descargar un
modelo, consultar el actual y entrar en la configuración avanzada. Si todavía
no hay un modelo, Nox ofrece `qwen3:4b` como recomendación inicial y también
permite escribir cualquier nombre publicado en Ollama.

Nox consulta primero los modelos que Ollama ya tiene instalados. Un modelo
existente se puede seleccionar directamente y nunca se vuelve a descargar,
incluso si se escribe manualmente su nombre en el flujo de descarga.

Los mismos pasos se pueden automatizar con comandos directos:

```powershell
nox models list
nox models install <modelo>
nox models use <modelo> --scope global
nox models use <modelo> --scope local
nox models actual
nox models remove <modelo>
```

Descargar y eliminar siempre requiere confirmación. Los comandos aceptan
`--json`; para confirmar una automatización se agrega `--yes`.
Al eliminar el modelo seleccionado, Nox también limpia esa selección en la
configuración general y en el proyecto activo para no dejarla obsoleta.

La API local predeterminada es `http://127.0.0.1:11434`. Si Ollama está en
otra dirección:

```powershell
nox config models --ollama-url http://servidor:11434 --scope global
```

## Iniciar una conversación

Desde el directorio del proyecto:

```powershell
nox start
```

Si el proyecto todavía no tiene `.nox`, Nox muestra la ruta exacta y pregunta
si debe ejecutar la inicialización. Después comprueba, en orden, que Ollama esté
disponible, que el servicio responda y que haya un modelo instalado y
seleccionado. El REPL solamente se abre cuando esos pasos están listos.
La inicialización y el registro se realizan una sola vez. Si Ollama está
instalado pero detenido, Nox permite iniciarlo y reintentar la conexión; para
un endpoint remoto solamente ofrece reintentar, sin iniciar procesos locales.

La sesión conserva el historial solamente en memoria. Sus comandos internos
son:

```text
/help o /ayuda       Muestra la ayuda
/status o /estado    Muestra el contexto activo
/clear o /limpiar    Limpia la conversación
/exit o /salir       Termina Nox
```

La `/` es obligatoria para los comandos internos. Cualquier entrada sin `/`,
incluidas palabras como `help`, `clear` o `exit`, se envía al modelo local como
parte de la conversación.

La conversación diferencia claramente a cada participante. Mientras el modelo
prepara la respuesta, Nox mantiene visible un estado de actividad:

```text
You> Hola?

Nox> Pensando...
```

Cuando llega el primer fragmento, esa misma línea se transforma en:

```text
Nox> ¡Hola! ¿En qué puedo ayudarte?

You>
```

`Pensando...` se reemplaza cuando llega el primer fragmento de la respuesta y
también se limpia de forma controlada si la generación se cancela o falla.

`Ctrl+C` se maneja como una cancelación controlada: vuelve desde los menús,
cancela la entrada o respuesta actual dentro del REPL y, en un comando directo,
termina con el código de salida `130` sin mostrar un traceback.

Esta primera versión del REPL conversa con el modelo, pero todavía no ejecuta
herramientas ni modifica archivos.

## Salir del entorno

```powershell
deactivate
```
