#!/usr/bin/env bash
set -euo pipefail

# Launch the Flask web UI for the capacity planner.
# Creates/uses .venv in the repo root.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${ROOT_DIR}/.venv"
HOST_ADDR="${HOST:-127.0.0.1}"
PORT_NUM="${PORT:-5151}"
REQUIREMENTS_FILE="${ROOT_DIR}/requirements-web.txt"

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  echo "python"  # fallback; script will fail later if unavailable
}

PY_CMD="$(ensure_python)"

# --- Create or repair venv ---
if [ ! -d "${VENV_PATH}" ]; then
  echo "Creating virtual environment at ${VENV_PATH}"
  "${PY_CMD}" -m venv "${VENV_PATH}"
fi

if [ ! -f "${VENV_PATH}/bin/activate" ]; then
  echo "Virtual environment missing 'activate' script; recreating..."
  rm -rf "${VENV_PATH}"
  "${PY_CMD}" -m venv "${VENV_PATH}"
fi

# Ensure pip/setuptools/wheel exist & are reasonably current
"${VENV_PATH}/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"${VENV_PATH}/bin/python" -m pip install --upgrade --disable-pip-version-check pip setuptools wheel >/dev/null 2>&1 || true

# shellcheck disable=SC1091
source "${VENV_PATH}/bin/activate"

# --- Verify requirements-web.txt are satisfied (without always reinstalling) ---
check_requirements() {
  local req_file="$1"
  if [ ! -f "${req_file}" ]; then
    echo "Requirements file not found: ${req_file}" >&2
    return 1
  fi

  "${VENV_PATH}/bin/python" - <<'PY' "${req_file}"
import sys
from pathlib import Path
import pkg_resources  # provided by setuptools

req_path = Path(sys.argv[1])
requirements = []
for line in req_path.read_text().splitlines():
    s = line.strip()
    if s and not s.startswith("#"):
        requirements.append(s)

if not requirements:
    sys.exit(0)

try:
    pkg_resources.require(requirements)
except (pkg_resources.DistributionNotFound, pkg_resources.VersionConflict):
    sys.exit(1)
PY
}

if ! check_requirements "${REQUIREMENTS_FILE}"; then
  echo "Installing web dependencies"
  "${VENV_PATH}/bin/python" -m pip install -r "${REQUIREMENTS_FILE}"
else
  echo "Web dependencies already satisfied"
fi

export FLASK_APP="webapp.app:create_app"
# Optional dev toggle: export FLASK_DEBUG=1

# --- Quick port preflight (fail early if busy) ---
if command -v lsof >/dev/null 2>&1 && lsof -i :"${PORT_NUM}" >/dev/null 2>&1; then
  echo "Error: Port ${PORT_NUM} is already in use. Set PORT=<free_port> and retry." >&2
  exit 1
fi

# --- Self-heal stale 'bin/flask' shebang if the venv was moved/copied ---
FLASK_SCRIPT="${VENV_PATH}/bin/flask"
if [ -f "${FLASK_SCRIPT}" ]; then
  FIRST_LINE="$(head -n 1 "${FLASK_SCRIPT}" || true)"
  case "${FIRST_LINE}" in
    \#\!* )
      if ! printf '%s' "${FIRST_LINE}" | grep -q "${VENV_PATH}/bin/python"; then
        echo "Detected stale flask entry point; reinstalling Flask..."
        "${VENV_PATH}/bin/python" -m pip install --force-reinstall --no-cache-dir Flask >/dev/null
      fi
      ;;
  esac
fi

# --- Ensure Flask and pandas are installed in the venv (idempotent) ---
if ! "${VENV_PATH}/bin/python" -m flask --version >/dev/null 2>&1; then
  echo "Flask not found — installing..."
  "${VENV_PATH}/bin/python" -m pip install -r "${REQUIREMENTS_FILE}" >/dev/null
fi

if ! "${VENV_PATH}/bin/python" -c "import pandas" >/dev/null 2>&1; then
  echo "Pandas not found — installing..."
  "${VENV_PATH}/bin/python" -m pip install pandas >/dev/null
fi

echo "Starting Flask app on ${HOST_ADDR}:${PORT_NUM}"
# Prefer invoking via python -m to avoid shebang/PATH issues
exec "${VENV_PATH}/bin/python" -m flask run --host="${HOST_ADDR}" --port="${PORT_NUM}"