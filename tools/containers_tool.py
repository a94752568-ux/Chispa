import subprocess
import time

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "containers_status",
        "description": "USAR CUANDO el usuario pregunte por contenedores, Waydroid o Docker en su equipo ('¿tengo docker?', 'estado de waydroid', '¿qué apps corren en contenedores?'). Detecta automáticamente cuál está disponible y reporta su estado. Sin argumentos.",
        "parameters": {"type": "object", "properties": {}}
    }
}
def _check_waydroid():
    """Verifica estado de Waydroid y lista apps Android."""
    try:
        # Verificar si waydroid está activo
        result = subprocess.run(
            ["waydroid", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        
        if result.returncode == 0 and "is running" in result.stdout.lower():
            # Waydroid está activo, listar paquetes
            result = subprocess.run(
                ["waydroid", "shell", "pm", "list", "packages", "-3"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            
            if result.returncode == 0:
                packages = [line.replace("package:", "").strip() for line in result.stdout.split('\n') if line.startswith("package:")]
                return f"Waydroid activo. Apps Android de terceros instaladas ({len(packages)}):\n" + "\n".join(packages[:20]) + ("\n...y más" if len(packages) > 20 else "")
            else:
                return "Waydroid activo pero no se pudieron listar los paquetes"
        else:
            return "Sesión detenida"
    except FileNotFoundError:
        return "Waydroid no instalado"
    except subprocess.TimeoutExpired:
        return "Timeout verificando Waydroid"
    except Exception as e:
        return f"Error verificando Waydroid: {e}"
def _check_docker():
    """Verifica estado de Docker y contenedores."""
    try:
        # Verificar si Docker está activo
        result = subprocess.run(
            ["docker", "ps", "--format", "table", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        
        if result.returncode == 0:
            containers = [line.strip() for line in result.stdout.split('\n') if line.strip()]
            result = subprocess.run(
                ["docker", "images", "--format", "table", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            
            images = []
            if result.returncode == 0:
                images = [line.strip() for line in result.stdout.split('\n') if line.strip()]
            
            return f"Docker activo. Contenedores ({len(containers)}):\n" + "\n".join(containers[:10]) + ("\n...y más" if len(containers) > 10 else "") + f"\nImágenes ({len(images)}):\n" + "\n".join(images[:10]) + ("\n...y más" if len(images) > 10 else "")
        else:
            return "Docker no activo"
    except FileNotFoundError:
        return "Docker no instalado"
    except subprocess.TimeoutExpired:
        return "Timeout verificando Docker"
    except Exception as e:
        return f"Error verificando Docker: {e}"
def execute() -> str:
    """Verifica si Waydroid o Docker está disponible y reporta según lo que exista."""
    # Intentar Waydroid primero (caso real)
    waydroid_result = _check_waydroid()
    
    if "Waydroid no instalado" in waydroid_result or "Sesión detenida" in waydroid_result:
        # Waydroid no está disponible, intentar Docker
        docker_result = _check_docker()
        return docker_result
    
    return waydroid_result