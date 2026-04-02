#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/ivkhokhlov/whisper-webui-mlx.git"

usage() {
    cat <<'EOF'
Whisper WebUI (MLX) installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/ivkhokhlov/whisper-webui-mlx/master/scripts/install.sh | bash

Options:
  --repo URL       Override git repository URL (default: https://github.com/ivkhokhlov/whisper-webui-mlx.git)
  --dir PATH       Install directory (default: $HOME/.local/share/whisper-webui-mlx)
  --bin-dir PATH   Directory for the launcher script (default: $HOME/.local/bin)
  -h, --help       Show this help

After installation, ensure that your bin-dir (e.g. $HOME/.local/bin) is on your PATH,
then you can run:

  whisper-webui-mlx
  whisper-webui-mlx --with-cohere

Bootstrap expectations:
  - macOS arm64: installs Whisper MLX as the default local backend
  - macOS Intel: installs Whisper CPU as the default local backend
  - --with-cohere: adds the optional Cohere SDK on either architecture
  - Parakeet is not installed by the macOS bootstrap path
EOF
}

REPO_URL="$REPO_URL_DEFAULT"
INSTALL_DIR="${HOME}/.local/share/whisper-webui-mlx"
BIN_DIR="${HOME}/.local/bin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO_URL="${2:-}"
            shift 2
            ;;
        --dir)
            INSTALL_DIR="${2:-}"
            shift 2
            ;;
        --bin-dir)
            BIN_DIR="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n\n' "$1" >&2
            usage
            exit 1
            ;;
    esac
done

printf 'Installing Whisper WebUI (MLX)\n'
printf '  Repo:   %s\n' "$REPO_URL"
printf '  Target: %s\n' "$INSTALL_DIR"
printf '  Bin:    %s\n' "$BIN_DIR"
if [[ "$(uname -s)" == "Darwin" ]]; then
    case "$(uname -m)" in
        arm64)
            printf '  Engine: Apple Silicon detected; first run defaults to Whisper MLX.\n'
            ;;
        x86_64)
            printf '  Engine: Intel macOS detected; first run defaults to Whisper CPU.\n'
            ;;
        *)
            printf '  Engine: macOS detected; architecture-specific bootstrap will run on first launch.\n'
            ;;
    esac
else
    printf '  Engine: bootstrap is architecture-aware and will explain local engine support on first launch.\n'
fi

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    printf 'Repository already exists, pulling latest changes...\n'
    git -C "$INSTALL_DIR" fetch --all --tags
    git -C "$INSTALL_DIR" pull --ff-only
else
    printf 'Cloning repository...\n'
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/whisper-webui-mlx"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$INSTALL_DIR"
exec "\${ROOT_DIR}/run.sh" "\$@"
EOF

chmod +x "$LAUNCHER"

printf '\nInstallation complete.\n'
printf 'Launcher created at: %s\n' "$LAUNCHER"
printf '\nMake sure %s is on your PATH.\n' "$BIN_DIR"
printf 'Then run:\n\n  whisper-webui-mlx\n\n'
printf 'Optional cloud backend:\n\n  whisper-webui-mlx --with-cohere\n\n'

