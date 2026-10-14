"""Verifica que .env se carga (sin dependencias) y con prioridad del entorno."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures = []


def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' :: ' + str(extra)) if extra else ''}")
    if not cond:
        failures.append(name)


# 1) Los valores del .env llegan a config
import config  # noqa: E402

check(".env leido: CAMPAIGN_MIN_DAYS", config.CAMPAIGN_MIN_DAYS == 15, config.CAMPAIGN_MIN_DAYS)
check(".env leido: HYBRID_ENABLED", config.HYBRID_ENABLED is True, config.HYBRID_ENABLED)
check(".env leido: BACKUP_TARGETS no vacio", bool(config.BACKUP_TARGETS), config.BACKUP_TARGETS)
check("targets validos (local/git/s3)",
      all(t in ("local", "git", "s3") for t in config.BACKUP_TARGETS), config.BACKUP_TARGETS)
# Invariante real: si se pide respaldo off-site por git, debe estar todo definido.
if "git" in config.BACKUP_TARGETS:
    check("BACKUP_GIT_REMOTE definido si targets incluye git",
          config.BACKUP_GIT_REMOTE.startswith("https://"), config.BACKUP_GIT_REMOTE)
    check("BACKUP_GIT_BRANCH definido", bool(config.BACKUP_GIT_BRANCH), config.BACKUP_GIT_BRANCH)

    # El token NO tiene por que estar en el .env: se resuelve con `gh auth token`.
    import backup_manager as bm  # noqa: E402

    check("token de push resoluble (BACKUP_GIT_TOKEN o 'gh auth token')",
          bool(bm.BackupManager._resolve_git_token()))
    check("el .env no expone el token en claro", "ghp_" not in (ROOT / ".env").read_text(encoding="utf-8"))
else:
    check("BACKUP_GIT_REMOTE vacio sin target git", config.BACKUP_GIT_REMOTE == "",
          config.BACKUP_GIT_REMOTE)

# 2) El entorno real tiene prioridad sobre el archivo
os.environ["HYBRID_MIN_FILL_RATIO"] = "0.77"
config._load_dotenv(ROOT / ".env")
check("entorno manda sobre .env",
      os.environ["HYBRID_MIN_FILL_RATIO"] == "0.77", os.environ["HYBRID_MIN_FILL_RATIO"])

# 3) Parser: comentarios, espacios, comillas y lineas rotas
tmp = ROOT / ".env.test"
tmp.write_text(
    "# comentario\n"
    "\n"
    "TEST_KEY_A=valor con espacios\n"
    'TEST_KEY_B="con comillas"\n'
    "TEST_KEY_C='simples'\n"
    "linea_rota_sin_igual\n"
    "=sin_clave\n",
    encoding="utf-8",
)
for k in ("TEST_KEY_A", "TEST_KEY_B", "TEST_KEY_C"):
    os.environ.pop(k, None)
config._load_dotenv(tmp)
check("valor con espacios", os.environ.get("TEST_KEY_A") == "valor con espacios",
      os.environ.get("TEST_KEY_A"))
check("comillas dobles", os.environ.get("TEST_KEY_B") == "con comillas", os.environ.get("TEST_KEY_B"))
check("comillas simples", os.environ.get("TEST_KEY_C") == "simples", os.environ.get("TEST_KEY_C"))
check("no rompe con lineas invalidas", os.environ.get("sin_clave") is None)
tmp.unlink()

# 4) .env inexistente no lanza
config._load_dotenv(ROOT / ".env.no_existe")
check(".env inexistente no rompe", True)

# 5) El parseo de .env no deja basura en el repo
check("sin archivos temporales", not list(ROOT.glob(".env.*")) or
      all(p.name == ".env.example" for p in ROOT.glob(".env.*")),
      [p.name for p in ROOT.glob(".env.*")])

print()
print("RESULTADO:", "TODOS LOS TESTS PASAN" if not failures else f"FALLOS: {failures}")
sys.exit(1 if failures else 0)
