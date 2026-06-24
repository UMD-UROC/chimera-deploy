#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

rm -rf docker/rosdep_src
mkdir -p docker/rosdep_src

find ros2_ws/src -name package.xml -print | sort | while read -r pkg; do
  rel_dir="$(dirname "$pkg" | sed 's#^ros2_ws/src/##')"
  mkdir -p "docker/rosdep_src/$rel_dir"
  cp "$pkg" "docker/rosdep_src/$rel_dir/package.xml"
done
