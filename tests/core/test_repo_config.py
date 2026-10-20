"""Конфигурация репозитория: .env.example полон, секретов нет."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRET_VARS = ("OUTPUT_SMB_USER", "OUTPUT_SMB_PASSWORD", "WEB_PASSWORD")


def _env_example() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


# Переменные, которые задаёт сам compose/образ (не пользователь), в .env.example не нужны.
INTERNAL_VARS = {"DATA_DIR", "MODELS_DIR", "HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"}
_CODE_ENV_RE = re.compile(
    r"""(?:environ|getenv|env)\s*(?:\.get\s*\(|\[|\()\s*["']([A-Z][A-Z0-9_]*)["']""")


def _code_env_vars() -> dict[str, str]:
    found = {}
    for path in (ROOT / "core").rglob("*.py"):
        for name in _CODE_ENV_RE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, path.relative_to(ROOT).as_posix())
    return found


def test_env_example_lists_every_compose_variable():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    missing = used - set(_env_example())
    assert not missing, f"нет в .env.example: {sorted(missing)}"


def test_env_example_lists_every_variable_read_by_core():
    used = _code_env_vars()
    assert "OUTPUT_SMB_HOST" in used  # сканер действительно видит чтения из окружения
    missing = {k: v for k, v in used.items() if k not in _env_example() and k not in INTERNAL_VARS}
    assert not missing, f"нет в .env.example: {missing}"


def test_env_example_has_spec_defaults_and_empty_secrets():
    env = _env_example()
    for key in SECRET_VARS:
        assert env[key] == "", key
    assert env["OUTPUT_KIND"] == "smb"
    assert env["OUTPUT_SMB_HOST"] == "192.168.0.129"
    assert env["OUTPUT_SMB_SHARE"] == "karaoke"
    assert env["LOCAL_OUTPUT_ROOT"] == "./output"
    assert env["DEFAULT_COMPUTE_TYPE"] == "int8"
    assert env["ULTRASINGER_GIT"] == "https://github.com/Kostec/UltraSinger.git#karaoke-local"


def test_env_example_variables_are_commented_in_russian():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            assert i > 0 and lines[i - 1].startswith("#") and re.search("[а-яё]", lines[i - 1], re.I), line


def test_dotenv_is_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and "!.env.example" in ignore


def test_no_passwords_in_repository():
    pattern = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN)[A-Z_]*[ \t]*[=:][ \t]*['\"]?([^\s'\"]+)", re.I)
    offenders = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT).as_posix()
        if (not path.is_file() or rel.startswith((".git/", ".autopilot/")) or rel == ".env"
                or "__pycache__" in rel or rel.startswith("tests/")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in pattern.finditer(text):
            value = m.group(2)
            if re.match(r"^(-\}|str\b|None\b|\$\{|os\.|env\.|self\.|target\.)", value):
                continue
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, offenders
