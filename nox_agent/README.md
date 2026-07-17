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
python -B -m nox_agent --help
```

## Salir del entorno

```powershell
deactivate
```
