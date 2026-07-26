# Nox Agent

Nox es la base de un agente personal y de desarrollo local. Se instala una
sola vez en Windows, reconoce cada espacio de trabajo mediante una carpeta
`.nox` y utiliza proveedores de inteligencia intercambiables para conversar y,
en el futuro, ejecutar capacidades de forma controlada.

La versión actual es **Nox 0.6.3**. Ya puede preparar Ollama, administrar
modelos y mantener una conversación local, pero todavía no ejecuta herramientas
ni controla la computadora.

## Por qué existe

Los modelos de inteligencia artificial ya pueden resolver tareas complejas,
pero depender exclusivamente de servicios pagos o de una conexión a Internet
deja al usuario sin una alternativa propia y confiable.

Nox busca resolver ese problema mediante dos componentes separados:

1. **Nox Agent** es el motor que conoce proyectos, configuración, proveedores,
   permisos y capacidades.
2. **La inteligencia usada por Nox** es intercambiable. Hoy proviene de un
   modelo ejecutado por Ollama. En el futuro podrá provenir de otros
   proveedores o de un modelo propio ajustado y destilado para Nox.

Nox no fue pensado solamente como un chatbot. La visión es que sea, al mismo
tiempo:

- Un agente personal multipropósito.
- Un agente de desarrollo.
- Una alternativa local que siga funcionando sin Internet una vez descargado
  el modelo.
- Un motor agnóstico del proveedor de inteligencia.
- Un sistema general instalado una sola vez, pero configurable por proyecto.

## Principios del proyecto

- **Local primero:** las capacidades esenciales deben poder funcionar en el
  equipo del usuario.
- **Agnóstico del modelo:** el núcleo no debe depender de Ollama, OpenAI,
  Claude ni de un modelo concreto.
- **Motor general, contexto local:** Nox vive en el sistema y `.nox` adapta su
  comportamiento a cada proyecto.
- **Pequeñas victorias:** cada versión debe ser comprensible, comprobable y
  útil por sí sola.
- **Seguridad antes de autonomía:** identificar, registrar y autorizar una
  acción debe ocurrir antes de permitir que un modelo la ejecute.
- **Configuración explícita:** las decisiones importantes deben poder
  consultarse desde el CLI y mediante respuestas estructuradas.

## Nox Agent y el modelo no son lo mismo

El paquete `nox_agent` es el motor de coordinación. Ollama es actualmente el
software que ejecuta modelos, y `qwen3:4b` es la recomendación inicial para
conversar.

Esta separación permite que las reglas de proyectos, permisos, herramientas y
auditoría pertenezcan a Nox en lugar de quedar encerradas dentro de un modelo.

## Arquitectura actual

```text
nox / CLI
├── proyecto y registro
│   ├── identidad .nox
│   └── relaciones raíz, padre e hijo
├── configuración
│   ├── general del usuario
│   └── local del proyecto
├── engines
│   └── instalación y proceso de Ollama
├── models
│   ├── contrato agnóstico
│   └── implementación de Ollama
├── runtime
│   ├── preparación de la sesión
│   ├── estado interno
│   └── REPL conversacional
└── tools
    ├── menús y terminal
    ├── confirmaciones
    ├── validaciones
    └── escritura segura de archivos
```

La carpeta interna `tools` contiene utilidades usadas por el programa. Todavía
no es un catálogo de herramientas que el modelo pueda ejecutar.

Los dominios principales del código son:

- `project.py`: inicialización, descubrimiento, manifiesto y relaciones entre
  proyectos.
- `registry.py`: índice general de proyectos conocidos por Nox.
- `config/`: catálogo, persistencia, menú y comandos de configuración.
- `engines/`: instalación, detección e inicio del software que ejecuta modelos.
- `models/`: contratos de proveedores, administración de modelos e inferencia.
- `runtime/`: preparación, estado y conversación.
- `errors.py` y `logs.py`: errores controlados y diagnóstico operativo.
- `tools/`: utilidades compartidas del CLI.

## Estado de la versión 0.6.3

| Capacidad | Estado actual |
|---|---|
| MSI por usuario y comando global `nox` | Disponible |
| Información de versión y ayuda | Disponible |
| Menú interactivo de Windows | Disponible |
| Inicialización y validación de `.nox` | Disponible |
| Proyectos `.nox` anidados | Disponible |
| Configuración general y local | Disponible |
| Respuestas JSON para automatizaciones | Disponible |
| Instalación y recuperación de Ollama | Disponible |
| Listado, descarga, selección y eliminación de modelos | Disponible |
| Chat local con streaming | Disponible |
| Proveedores diferentes de Ollama | Contrato preparado; no implementados |
| Contexto humano específico del proyecto | Planificado para 0.7 |
| Identificación estructurada de intenciones | Planificada para 0.7 |
| Herramientas ejecutables por el agente | No implementadas |
| Permisos y auditoría persistente | No implementados |
| Memoria persistente | No implementada |
| Modelo propio, fine-tuning y destilación | Investigación futura |

## Instalación del producto

El MSI instala Nox por usuario en `%LOCALAPPDATA%\Programs\Nox`, agrega el
ejecutable al `PATH` y registra el producto en las aplicaciones instaladas de
Windows.

El programa congelado incluye el runtime que necesita. La computadora donde se
instala Nox no necesita tener Python ni cx-Freeze.

La desinstalación estándar retira el programa instalado. Todavía no existe una
acción de desinstalación profunda que recorra los proyectos y elimine sus
carpetas `.nox`, ni que quite la configuración, el registro y los logs
guardados fuera del directorio del programa.

## Desarrollo y fábrica

La fábrica actual utiliza:

- CPython 3.14.6 x64.
- Un entorno virtual en `.venv`.
- cx-Freeze 8.6.4.

### Activar el entorno local

Desde esta carpeta:

```powershell
.\.venv\Scripts\Activate.ps1
```

Luego, para que Python encuentre el paquete `nox_agent` mientras desarrollamos:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

### Probar el comando principal

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

### Generar el MSI

Con el entorno activado:

```powershell
python -m cx_Freeze bdist_msi
```

El ejecutable congelado se genera dentro de `build/` y el instalador final
dentro de `dist/`. Estas carpetas son artefactos locales y no se versionan.

## Inicio rápido

Después de instalar el MSI:

```powershell
nox --version
cd <proyecto>
nox init
nox models
nox start
```

`nox models` guía la preparación de Ollama y la selección de un modelo.
`nox start` también puede realizar esa preparación y ofrecer la inicialización
del proyecto cuando todavía no existe `.nox`.

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

## Estado estructurado de Nox

Nox expone un comando oculto pensado para autoidentificación y consumo por
otros agentes:

```powershell
nox --status
```

La respuesta JSON contiene versión, entorno, proyecto activo, configuración,
sesión, registro y capacidades declaradas.

Este estado es descriptivo: una sesión aparece preparada cuando existe un
proyecto y hay un modelo configurado. No reemplaza una comprobación real de que
Ollama esté instalado y respondiendo; `nox models list` sí realiza esa
conexión.

## Dónde se guarda la información

| Ubicación | Contenido |
|---|---|
| `%LOCALAPPDATA%\Programs\Nox` | Programa instalado y runtime congelado |
| `%LOCALAPPDATA%\Nox\config.toml` | Configuración general del usuario |
| `%LOCALAPPDATA%\Nox\state\projects.json` | Registro de proyectos conocidos |
| `%LOCALAPPDATA%\Nox\state\ollama-*.lock` | Coordinación del inicio de Ollama |
| `%LOCALAPPDATA%\Nox\logs\ollama-serve.log` | Salida de `ollama serve` cuando Nox lo inicia |
| `<proyecto>\.nox\project.toml` | Identidad y relación padre/hijo |
| `<proyecto>\.nox\config.toml` | Configuración particular del proyecto |
| Memoria del proceso | Historial temporal de la conversación actual |

### Qué representa `.nox`

`.nox` es el vínculo entre un proyecto y el motor general instalado en el
equipo. Se excluye de Git por defecto porque fue pensado como contexto privado
del usuario.

En 0.6.3 contiene identidad y configuración. Todavía no contiene instrucciones
del proyecto, políticas, herramientas, memoria ni documentación contextual.

Un `.nox` puede vivir dentro de otro `.nox`. El hijo debe declarar la identidad
y ubicación relativa de su padre. Nox valida esa relación e informa si el
contexto activo es `RAÍZ`, `PADRE` o `HIJO`.

### Registro global

`projects.json` no almacena el contenido de los proyectos. Es un índice con su
identidad, ruta, relación con un padre y última vez que Nox lo vio.

Actualmente el registro no retira automáticamente entradas cuyas carpetas ya
no existen.

## Configuración general y local

La configuración se resuelve con esta precedencia:

```text
local del proyecto > general del usuario > valor predeterminado
```

Las opciones reales de 0.6.3 son:

- `logs.level`
- `models.provider`
- `models.model`
- `models.ollama_url`

`Memory` y `Security` sólo aparecen como secciones futuras y no tienen
comportamiento.

## Logs, auditoría y memoria

Son tres conceptos diferentes:

### Logs operativos

Ya existe una capa de logs y se puede elegir su nivel. Actualmente usa la
salida de la terminal para diagnósticos. Cuando Nox inicia directamente
`ollama serve`, la salida de ese proceso puede guardarse en
`%LOCALAPPDATA%\Nox\logs\ollama-serve.log`.

### Auditoría

Todavía no existe una auditoría persistente. Nox no guarda un historial
estructurado que indique:

- Qué intención detectó.
- Qué capacidad solicitó el modelo.
- Qué autorizó o rechazó el usuario.
- Qué herramienta se ejecutó.
- Qué resultado o error produjo.

La auditoría debe existir antes de habilitar herramientas que modifiquen
proyectos o controlen la computadora.

### Memoria

El historial del REPL vive únicamente en RAM y se pierde al cerrar la sesión.
Eso permite conversar, pero no constituye memoria de agente.

La memoria persistente se agregará al final del desarrollo de las capas
fundamentales. Primero deben estabilizarse contexto, intenciones, auditoría,
permisos y herramientas; de lo contrario Nox podría conservar información
incorrecta o acciones no confiables.

## Seguridad e integridad existentes

Aunque todavía no hay un sistema completo de permisos, 0.6.3 ya incorpora
algunas protecciones:

- Las operaciones externas destructivas piden confirmación.
- `--yes` existe para automatizaciones que ya fueron autorizadas.
- El instalador de Ollama se descarga desde sus releases oficiales.
- Se valida el SHA-256 publicado para el artefacto.
- Se valida la firma Authenticode, identidad, clave pública, uso de firma de
  código y sello de tiempo.
- Los archivos de configuración se reemplazan mediante temporales únicos en el
  mismo directorio.
- Los errores públicos utilizan códigos estables `EN0178xxx`.
- `Ctrl+C` se transforma en una cancelación controlada.

La identidad criptográfica reconocida para Ollama está fijada en el código. Si
el editor rota legítimamente su certificado o clave, será necesario publicar
una nueva versión de Nox que reconozca la nueva identidad.

## Límites y deuda conocida

- La agnosticidad del proveedor es todavía parcial: sólo Ollama está
  implementado.
- Los comandos de motores también están acoplados a Ollama.
- Nox es actualmente específico de Windows.
- `.nox` todavía no es un harness completo del agente.
- El REPL conversa, pero no puede leer proyectos mediante herramientas,
  ejecutar Git, modificar archivos ni controlar la PC.
- El historial se reenvía completo en cada turno y no tiene todavía una
  ventana o compactación.
- El estado interno puede informar que una sesión está preparada sin comprobar
  que Ollama esté respondiendo.
- El registro puede conservar proyectos que ya no existen.
- No hay una suite permanente de pruebas dentro del repositorio; las
  validaciones de esta etapa fueron manuales y temporales.
- La desinstalación profunda de datos generales y `.nox` sigue pendiente.

## Roadmap acordado

### 0.7: contexto e identificación de intenciones

La próxima versión convertirá `.nox` en una fuente real de contexto y agregará
la primera capacidad interna del agente: identificar qué pretende el usuario
antes de responder o actuar.

La capa de contexto deberá:

- Reunir identidad, raíz, rol padre/hijo y configuración efectiva.
- Incorporar instrucciones humanas específicas del proyecto mediante un
  formato todavía por acordar.
- Entregar una representación validada y agnóstica al resto de Nox.
- Mantener separado el contexto explícito de la futura memoria aprendida.

El identificador de intenciones no ejecutará herramientas por sí mismo.
Producirá una decisión estructurada y validable que permita distinguir, como
mínimo:

- Conversación general.
- Consulta sobre el proyecto.
- Solicitud de cambio en el proyecto.
- Operación sobre Nox.
- Acción sobre el sistema.
- Solicitud ambigua que requiere aclaración.

La decisión también deberá informar el ámbito, nivel de riesgo, capacidades
necesarias y confianza. Una clasificación inválida o de baja confianza nunca
deberá transformarse automáticamente en una acción.

Los comandos explícitos del CLI y los comandos `/` del REPL seguirán siendo
deterministas. El clasificador se utilizará para lenguaje natural, mediante un
contrato propio de Nox que no dependa del proveedor elegido.

### Después de 0.7

El orden previsto es:

1. Auditoría persistente de sesiones, intenciones, autorizaciones y acciones.
2. Políticas de permisos y confirmaciones según riesgo.
3. Primera herramienta de sólo lectura sobre el proyecto.
4. Herramientas de escritura y desarrollo.
5. Más adaptadores de proveedores.
6. Capacidades personales y de control de la computadora.
7. Memoria persistente, una vez que el comportamiento sea confiable.

El desarrollo de un modelo propio, su fine-tuning y su destilación es una línea
de investigación posterior. Nox Agent debe poder avanzar y ser útil antes de
que ese modelo exista.

## Cierre de 0.6.3

Esta versión consolida:

- Instalador MSI por usuario.
- CLI interactivo y automatizable.
- Proyectos `.nox` y relaciones padre/hijo.
- Configuración general y local.
- Instalación verificada de Ollama.
- Administración de modelos sin descargas duplicadas.
- REPL local con streaming, `You>`, `Nox>` y `Pensando...`.
- Cancelación controlada mediante `Ctrl+C`.
- Compatibilidad con CMD clásico sin secuencias ANSI visibles.
- Escrituras atómicas con temporales únicos.
- Validación de que la raíz del proyecto siga existiendo.

## Salir del entorno

```powershell
deactivate
```
