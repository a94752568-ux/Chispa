#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-qwen2.5-coder:latest}"
PROMPT="${2:-Responde con exactamente una frase: hola mundo.}"
OUT="${3:-/tmp/ollama_raw_$(date +%Y%m%d_%H%M%S).jsonl}"

echo "Modelo: $MODEL" >&2
echo "Prompt: $PROMPT" >&2
echo "Salida raw: $OUT" >&2

# Use jq to properly escape the JSON to avoid quoting issues
PAYLOAD=$(jq -n \
  --arg model "$MODEL" \
  --arg role "user" \
  --arg content "$PROMPT" \
  '{"model": $model, "messages": [{"role": $role, "content": $content}], "stream": true}')

curl -N -s http://127.0.0.1:11434/api/chat \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" | tee "$OUT"

ANALYSIS="${OUT%.jsonl}_analysis.txt"

{
  echo "=== Chunks ==="
  jq -c '{
    created_at,
    done,
    done_reason,
    content_len: (.message.content | length),
    content: .message.content
  }' "$OUT"

  echo
  echo "=== Duplicados consecutivos por content ==="
  jq -c '.message.content // ""' "$OUT" | uniq -c | awk '$1 > 1'

  echo
  echo "=== Duplicados exactos ignorando created_at ==="
  jq -c 'del(.created_at) | {
    model,
    done,
    done_reason,
    content: .message.content
  }' "$OUT" |
  awk '{count[$0]++} END {for (k in count) if (count[k] > 1) print count[k], k}'

} > "$ANALYSIS"

echo "Análisis guardado en: $ANALYSIS" >&2