import importlib.util
from pathlib import Path
import traceback

# ⚠️ ÚNICO PUNTO DE VERDAD de las tools de MUTACIÓN (escritura).
# Si añades una tool de escritura, regístrala aquí: una tool de escritura
# no registrada se ejecutará sin pedir permiso al usuario.
MUTACIONES = {"write_desktop", "organize_files", "db_writer", "move_file", "delete_file"}


def get_tools_dir():
    """Busca carpeta tools en múltiples ubicaciones (dev y PyInstaller bundle)"""
    candidates = []
    candidates.append(Path(__file__).parent / "tools")
    candidates.append(Path(__file__).parent.parent / "tools")

    if hasattr(__import__('sys'), '_MEIPASS'):
        candidates.append(Path(__import__('sys')._MEIPASS) / "tools")

    candidates.append(Path(__import__('sys').executable).parent / "tools")
    candidates.append(Path.cwd() / "tools")

    seen = set()
    result = []
    for c in candidates:
        try:
            resolved = c.resolve()
            if resolved.exists() and str(resolved) not in seen:
                result.append(resolved)
                seen.add(str(resolved))
        except Exception:
            pass

    return result


def load_tools():
    """Carga todos los tools de la carpeta tools/"""
    definitions = []
    executors = {}

    tools_dirs = get_tools_dir()
    if not tools_dirs:
        print("⚠ No se encontró carpeta tools en ninguna ubicación")
        return definitions, executors

    print(f"🔍 Buscando tools en: {tools_dirs}")

    loaded_files = set()

    for tools_dir in tools_dirs:
        for file in tools_dir.glob("*.py"):
            if file.name.startswith("_") or file.name == "__init__.py":
                continue
            if file.name in loaded_files:
                continue
            loaded_files.add(file.name)

            try:
                spec = importlib.util.spec_from_file_location(file.stem, file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, "TOOL_DEFINITION") and hasattr(mod, "execute"):
                    definitions.append(mod.TOOL_DEFINITION)
                    executors[mod.TOOL_DEFINITION["function"]["name"]] = mod.execute
                    print(f"✓ Tool cargado: {mod.TOOL_DEFINITION['function']['name']} desde {file}")
            except Exception as e:
                print(f"✗ Error cargando tool {file.name}: {e}")
                traceback.print_exc()

    if not definitions:
        print("⚠ Ningún tool cargado")

    return definitions, executors


def get_available_tool_names():
    names = []
    for tools_dir in get_tools_dir():
        for file in tools_dir.glob("*.py"):
            if file.name.startswith("_") or file.name == "__init__.py":
                continue
            names.append(file.stem)
    return list(set(names))
