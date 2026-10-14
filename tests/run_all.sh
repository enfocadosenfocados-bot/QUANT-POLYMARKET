#!/usr/bin/env bash
# Ejecuta toda la bateria de tests del bot (persistencia, modo hibrido, API, config).
# Uso:  bash tests/run_all.sh        (desde la raiz del proyecto)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$ROOT" || exit 1
fail=0

for t in test_dotenv test_hybrid test_hybrid_api test_persistence test_shutdown; do
    echo "=============================================================="
    echo "== $t"
    echo "=============================================================="
    if ! "$PY" "tests/$t.py"; then
        fail=1
        echo "!! FALLO EN $t"
    fi
    echo
done

echo "=============================================================="
if [ "$fail" -eq 0 ]; then
    echo "TODA LA BATERIA PASA"
else
    echo "HAY FALLOS (ver arriba)"
fi
exit "$fail"
