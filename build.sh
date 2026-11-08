#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[1/4] Creando venv..."
python3 -m venv venv 2>/dev/null || python -m venv venv || true
source venv/bin/activate || source venv/Scripts/activate 2>/dev/null || true

echo "[2/4] Instalando dependencias GUI..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo "[3/4] Verificando Lubuntu deps (opcional)..."
sudo apt update && sudo apt install -y libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 2>/dev/null || echo "Si el ejecutable no abre, ejecuta: sudo apt install libxcb-cursor0 libxcb-xinerama0"

echo "[4/4] Compilando GUI para Lubuntu..."

# Detectar carpeta tools
TOOLS_ARG=""
if [ -d "tools" ]; then
    echo "✓ Carpeta tools encontrada, se incluirá en el ejecutable"
    TOOLS_ARG="--add-data \"$SCRIPT_DIR/tools:tools\""
else
    echo "⚠ Carpeta tools NO encontrada en $SCRIPT_DIR, compilando sin ella"
    echo "  La app buscará tools/ junto al ejecutable en runtime"
fi

# Intentar con windowed, si falla usar console para ver errores
if [ -n "$TOOLS_ARG" ]; then
    echo "Comando: pyinstaller --onefile --windowed --name OllamaChat-GUI ... --add-data tools:tools main.py"
    pyinstaller --onefile --windowed \
      --name OllamaChat-GUI \
      --clean \
      --collect-all PySide6 \
      --collect-all shiboken6 \
      --hidden-import=ollama \
      --hidden-import=requests \
      --hidden-import=PIL \
      --hidden-import=markdown \
      --add-data "$SCRIPT_DIR/tools:tools" \
      main.py || {
        echo "⚠ Falló con windowed, intentando con console y sin collect-all..."
        pyinstaller --onefile \
          --name OllamaChat-GUI \
          --clean \
          --hidden-import=ollama \
          --add-data "$SCRIPT_DIR/tools:tools" \
          main.py
    }
else
    # Sin tools
    pyinstaller --onefile --windowed \
      --name OllamaChat-GUI \
      --clean \
      --collect-all PySide6 \
      --collect-all shiboken6 \
      --hidden-import=ollama \
      main.py || pyinstaller --onefile --name OllamaChat-GUI --clean main.py
fi

echo ""
if [ -f "dist/OllamaChat-GUI" ]; then
    echo "✅ Ejecutable GUI creado: ./dist/OllamaChat-GUI"
    echo "   Tamaño: $(du -h dist/OllamaChat-GUI | cut -f1)"
    echo "   Ejecuta: ./dist/OllamaChat-GUI"
    echo ""
    echo "Si usas modo onefile sin tools embebidos, copia la carpeta tools junto al binario:"
    echo "  cp -r tools dist/"
    echo "  ./dist/OllamaChat-GUI"
    echo ""
    echo "Para instalar en menu Lubuntu:"
    echo "  sudo mv dist/OllamaChat-GUI /usr/local/bin/"
    echo "  cp ollama-chat.desktop ~/.local/share/applications/"
else
    echo "❌ Build falló, no se creó dist/OllamaChat-GUI"
    echo "Intenta build manual:"
    echo "  pyinstaller --onefile --windowed main.py"
    exit 1
fi
