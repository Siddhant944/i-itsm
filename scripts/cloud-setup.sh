#!/usr/bin/env bash
# Paste the body of this script into the Claude Code cloud environment's setup script
# (or run it on any Linux box). It installs project dependencies and the three
# helper tools into ./tools: gitleaks (built from proxy.golang.org), PlantUML
# (Maven Central) and tectonic (conda-forge via micromamba). Safe to re-run.
set -euo pipefail

# Works when run as a file or pasted into a setup script (no BASH_SOURCE then).
REPO="${REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$REPO"
[ -f backend/pyproject.toml ] || { echo "cloud-setup: run from the repository root (or set REPO)" >&2; exit 1; }
for tool in uv npm curl; do
  command -v "$tool" >/dev/null || { echo "cloud-setup: $tool is required" >&2; exit 1; }
done
TOOLS="$REPO/tools"
mkdir -p "$TOOLS/bin"

GITLEAKS_VERSION=v8.30.1
PLANTUML_VERSION=1.2026.9
MICROMAMBA_VERSION=2.10.0
TECTONIC_VERSION=0.17.0

# Project dependencies (uv provisions Python 3.12 itself when missing).
(cd backend && uv sync)
(cd frontend && npm ci)
(cd e2e && npm ci)

# gitleaks
if [ ! -x "$TOOLS/bin/gitleaks" ]; then
  command -v go >/dev/null || { echo "cloud-setup: Go is required to build gitleaks" >&2; exit 1; }
  GOBIN="$TOOLS/bin" go install "github.com/zricethezav/gitleaks/v8@${GITLEAKS_VERSION}"
fi

# PlantUML (Java is required to render)
if [ ! -f "$TOOLS/plantuml.jar" ]; then
  curl -fsSL -o "$TOOLS/plantuml.jar" \
    "https://repo1.maven.org/maven2/net/sourceforge/plantuml/plantuml/${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar"
fi

# tectonic, via a throwaway micromamba
if [ ! -x "$TOOLS/tex/bin/tectonic" ]; then
  curl -fsSL "https://conda.anaconda.org/conda-forge/linux-64/micromamba-${MICROMAMBA_VERSION}-0.tar.bz2" \
    | tar -xj -C "$TOOLS" bin/micromamba
  MAMBA_ROOT_PREFIX="$TOOLS/mamba" "$TOOLS/bin/micromamba" create -y -q \
    -p "$TOOLS/tex" -c conda-forge "tectonic=${TECTONIC_VERSION}"
  rm -rf "$TOOLS/mamba/pkgs"
fi

# Git hooks
if [ -d .git ]; then (cd backend && uv run pre-commit install); fi

echo "cloud-setup: done"
