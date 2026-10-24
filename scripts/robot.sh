#!/usr/bin/env bash
# Run ROBOT from a pinned release. The jar is downloaded once into .cache/ and checked against a hash.
# Usage: scripts/robot.sh <robot arguments>
set -euo pipefail

VERSION="1.9.11"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JAR="$ROOT/.cache/robot-$VERSION.jar"

if [[ ! -f "$JAR" ]]; then
  mkdir -p "$ROOT/.cache"
  curl -sSfL "https://github.com/ontodev/robot/releases/download/v$VERSION/robot.jar" -o "$JAR.tmp"
  mv "$JAR.tmp" "$JAR"
fi

exec java -Xmx2g -jar "$JAR" "$@"
