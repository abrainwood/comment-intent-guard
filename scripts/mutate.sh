#!/bin/sh
set -eu

MUTMUT_VERSION="3.8.0"
PYTEST_VERSION="9.1.1"
PYYAML_VERSION="6.0.3"
PYTEST_XDIST_VERSION="3.6.1"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
VENV_DIR="$ROOT_DIR/.venv-mutate"
PATCH_DIR="$ROOT_DIR/scripts/mutmut-patches"
NOISE_FILE="$ROOT_DIR/scripts/mutmut-known-equivalent.txt"
PYTHON="${PYTHON:-python3}"

usage() {
  cat >&2 <<EOF
usage: scripts/mutate.sh [--with-subprocess-coverage] [mutant-name-glob ...]

  --with-subprocess-coverage  credit tests that reach the code through a
                              spawned process (slow, full audit)
  mutant-name-glob            limit the run, e.g. 'hooks.session_start.*'
EOF
  exit 2
}

ensure_venv() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
  fi
  "$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check \
    "mutmut==$MUTMUT_VERSION" "pytest==$PYTEST_VERSION" "pyyaml==$PYYAML_VERSION" \
    "pytest-xdist==$PYTEST_XDIST_VERSION"
}

apply_patches() {
  site_packages="$("$VENV_DIR/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  for patch_file in "$PATCH_DIR"/*.patch; do
    if patch --dry-run --reverse --force --silent -p1 -d "$site_packages" < "$patch_file" >/dev/null 2>&1; then
      continue
    fi
    patch --forward --silent -p1 -d "$site_packages" < "$patch_file"
  done
}

report_results() {
  raw_file="$(mktemp)"
  mutmut results > "$raw_file"

  noise_patterns_file="$(mktemp)"
  if [ -f "$NOISE_FILE" ]; then
    grep -v '^[[:space:]]*#' "$NOISE_FILE" | grep -v '^[[:space:]]*$' > "$noise_patterns_file" || true
  fi

  if [ -s "$noise_patterns_file" ]; then
    filtered_file="$(mktemp)"
    grep -v -F -f "$noise_patterns_file" "$raw_file" > "$filtered_file" || true
    suppressed=$(($(wc -l < "$raw_file") - $(wc -l < "$filtered_file")))
    cat "$filtered_file"
    rm -f "$filtered_file"
  else
    suppressed=0
    cat "$raw_file"
  fi

  if [ "$suppressed" -gt 0 ]; then
    echo
    echo "suppressed $suppressed known-equivalent mutant(s), see scripts/mutmut-known-equivalent.txt"
  fi

  rm -f "$raw_file" "$noise_patterns_file"
}

with_subprocess_coverage=0
case "${1:-}" in
  --with-subprocess-coverage)
    with_subprocess_coverage=1
    shift
    ;;
  -h|--help)
    usage
    ;;
esac

ensure_venv
apply_patches

cd "$ROOT_DIR"
rm -rf mutants
PATH="$VENV_DIR/bin:$PATH"
export PATH

if [ "$with_subprocess_coverage" -eq 1 ]; then
  MUTMUT_HITS_FILE="$VENV_DIR/subprocess-hits.txt"
  rm -f "$MUTMUT_HITS_FILE"
  export MUTMUT_HITS_FILE
else
  unset MUTMUT_HITS_FILE || true
fi

started_at="$(date +%s)"
mutmut run "$@"
finished_at="$(date +%s)"

report_results
echo "mutmut run wall-clock: $((finished_at - started_at))s"
