#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="${REPO_DIR}/skills"
SKILL_NAMES=("vibe-observability" "vibe-observability-loop")

TARGET="antigravity"
MODE="symlink"
ACTION="install"
DRY_RUN="false"
PROJECT_DIR=""

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Install or uninstall vibe-observability skills for your AI coding agent.

Options:
  --target <name>     Target agent environment (default: antigravity)
                      Values: antigravity | claude | codex | cursor | agents | project | all
  --project-dir <dir> Project root when --target project (default: current directory)
  --symlink           Install via symlinks so git pull updates skills automatically (default)
  --copy              Install full copies instead of symlinks
  --uninstall         Remove installed skills from the chosen target(s)
  --dry-run           Print planned actions without modifying the filesystem
  -h, --help          Show this help message

Examples:
  ./install.sh --target antigravity --symlink
  ./install.sh --target claude --copy
  ./install.sh --target project --project-dir /path/to/my-app
  ./install.sh --target all --symlink
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --symlink)
      MODE="symlink"
      shift
      ;;
    --copy)
      MODE="copy"
      shift
      ;;
    --uninstall)
      ACTION="uninstall"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown option '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

resolve_target_dirs() {
  local target="$1"
  case "$target" in
    antigravity)
      echo "${HOME}/.gemini/config/skills"
      ;;
    claude)
      echo "${HOME}/.claude/skills"
      ;;
    codex)
      echo "${HOME}/.codex/skills"
      ;;
    cursor)
      echo "${HOME}/.cursor/skills"
      ;;
    agents)
      echo "${HOME}/.agents/skills"
      ;;
    project)
      local base="${PROJECT_DIR:-$(pwd)}"
      echo "${base}/.agents/skills"
      ;;
    all)
      echo "${HOME}/.gemini/config/skills"
      echo "${HOME}/.claude/skills"
      echo "${HOME}/.codex/skills"
      echo "${HOME}/.cursor/skills"
      echo "${HOME}/.agents/skills"
      ;;
    *)
      echo "Error: Unsupported target '${target}'" >&2
      exit 2
      ;;
  esac
}

run_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

install_to_dir() {
  local dest_root="$1"
  run_cmd mkdir -p "${dest_root}"

  for skill in "${SKILL_NAMES[@]}"; do
    local src="${SKILLS_SRC}/${skill}"
    local dest="${dest_root}/${skill}"

    if [[ ! -d "${src}" ]]; then
      echo "Error: Source skill directory missing: ${src}" >&2
      exit 1
    fi

    if [[ -L "${dest}" || -e "${dest}" ]]; then
      run_cmd rm -rf "${dest}"
    fi

    if [[ "${MODE}" == "symlink" ]]; then
      run_cmd ln -s "${src}" "${dest}"
      echo "Linked   ${dest} -> ${src}"
    else
      run_cmd cp -R "${src}" "${dest}"
      echo "Copied   ${src} -> ${dest}"
    fi
  done
}

uninstall_from_dir() {
  local dest_root="$1"
  for skill in "${SKILL_NAMES[@]}"; do
    local dest="${dest_root}/${skill}"
    if [[ -L "${dest}" || -e "${dest}" ]]; then
      run_cmd rm -rf "${dest}"
      echo "Removed  ${dest}"
    else
      echo "Skipped  ${dest} (not installed)"
    fi
  done
}

while IFS= read -r dir; do
  [[ -z "${dir}" ]] && continue
  if [[ "${ACTION}" == "install" ]]; then
    install_to_dir "${dir}"
  else
    uninstall_from_dir "${dir}"
  fi
done < <(resolve_target_dirs "${TARGET}")

echo "Done (${ACTION}, target=${TARGET}, mode=${MODE})."
