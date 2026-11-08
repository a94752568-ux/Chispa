import importlib.util
from pathlib import Path
import sys
import traceback

def get_tools_dirs():
    """Busca carpeta tools en múltiples ubicaciones (dev y PyInstaller bundle)"""
    candidates = []
    
    # 1. Junto a este archivo (dev)
    candidates.append(Path(__file__).parent)
    
    # 2. PyInstaller _MEIPASS
    if hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys._MEIPASS) / "tools")
    
    # 3. Junto al ejecutable
    candidates.append(Path(sys.executable).parent / "tools")
    
    # 4. CWD/tools
    candidates.append(Path.cwd() / "tools")
    
    # 5. SCRIPT_DIR/tools (cuando se ejecuta python main.py)
    try:
        candidates.append(Path(__file__).parent.parent / "tools")
    except:
        pass
    
    # Filtrar existentes y únicos
    seen = set()
    result = []
    for c in candidates:
        try:
            resolved = c.resolve()
            if resolved.exists() and str(resolved) not in seen:
                result.append(resolved)
                seen.add(str(resolved))
        except:
            pass
    
    return result

def load_tools():
    """Carga todos los tools de la carpeta tools/"""
    definitions = []
    executors = {}
    
    tools_dirs = get_tools_dirs()
    if not tools_dirs:
        print("⚠ No se encontró carpeta tools en ninguna ubicación")
        print(f"  Buscado en: {[str(p) for p in [Path(__file__).parent, Path.cwd() / 'tools']]}")
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
    for tools_dir in get_tools_dirs():
        for file in tools_dir.glob("*.py"):
            if file.name.startswith("_") or file.name == "__init__.py":
                continue
            names.append(file.stem)
    return list(set(names))
