import subprocess
from pathlib import Path

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "git_status",
        "description": "USAR CUANDO el usuario pregunte por un repositorio git local: rama actual, últimos commits, cambios sin commitear o remotos ('¿en qué rama estoy?', 'estado del repo', 'últimos commits'). path es opcional (usa el directorio actual si no se especifica).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta del directorio del repo git (opcional, actual si no se especifica)"}
            },
            "required": []
        }
    }
}
def _safe_execute_git(args, path=None):
    """Ejecuta un comando git desde la whitelist con seguridad."""
    allowed_commands = {
        "status": ["git", "status", "--porcelain"],
        "log_n": ["git", "log", "-n", "10", "--oneline"],
        "branch": ["git", "branch", "--show-current"],
        "diff_stat": ["git", "diff", "--stat"],
        "remote_v": ["git", "remote", "-v"]
    }
    
    if not args or args not in allowed_commands:
        return f"Error: comando '{args}' no permitido"
    
    cmd = allowed_commands[args]
    try:
        result = subprocess.run(
            cmd,
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"Error: timeout ejecutando {args}"
    except Exception as e:
        return f"Error ejecutando {args}: {e}"
def execute(path: str = None) -> str:
    """Obtiene estado del git repo con whitelist estricta."""
    base_path = Path(path) if path else Path.cwd()
    
    if not base_path.exists():
        return f"Error: directorio '{base_path}' no existe"
    
    if not (base_path / ".git").exists():
        return f"Error: '{base_path}' no es un repo git"
    
    # Ejecutar los comandos permitidos
    results = []
    
    # Estado
    status_result = _safe_execute_git("status", str(base_path))
    results.append(f"=== Estado ===\n{status_result}")
    
    # Rama actual
    branch_result = _safe_execute_git("branch", str(base_path))
    results.append(f"=== Rama ===\n{branch_result}")
    
    # Últimos commits
    log_result = _safe_execute_git("log_n", str(base_path))
    results.append(f"=== Últimos commits ===\n{log_result}")
    
    # Diff --stat (cambios sin commitear)
    diff_result = _safe_execute_git("diff_stat", str(base_path))
    results.append(f"=== Cambios sin commitear ===\n{diff_result}")
    
    # Remotos
    remote_result = _safe_execute_git("remote_v", str(base_path))
    results.append(f"=== Remotos ===\n{remote_result}")
    
    return "\n".join(results)