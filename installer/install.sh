#!/usr/bin/env bash
# LoopMap installer for macOS and Linux
# Downloads the latest loopmap binary from GitHub Releases
# Run from the repo root: bash install.sh

set -e

REPO="bagusindrawanhardi/LoopMap"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

OS="$(uname -s)"
case "$OS" in
  Darwin) FILE="loopmap-macos" ;;
  Linux)  FILE="loopmap-linux" ;;
  *)      echo "Unsupported OS: $OS"; exit 1 ;;
esac

URL="https://github.com/$REPO/releases/latest/download/$FILE"
OUT="$DIR/loopmap"

echo "Downloading $FILE from GitHub Releases..."
if command -v curl &>/dev/null; then
  curl -fsSL "$URL" -o "$OUT"
elif command -v wget &>/dev/null; then
  wget -q "$URL" -O "$OUT"
else
  echo "Error: curl or wget is required."
  exit 1
fi

chmod +x "$OUT"
echo "Done. loopmap is ready in the repo root."
echo ""
echo "Usage:"
echo "  ./loopmap --project usecases/<your-topic> --serve"
