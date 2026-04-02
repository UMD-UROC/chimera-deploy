#!/bin/bash
set -e

# Usage check
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <source_dir> <converted_dir>"
  exit 1
fi

SOURCE_DIR="$1"
DEST_DIR="$2"

# Create destination directory if it doesn't exist
mkdir -p "$DEST_DIR"

# Find all unique .ts files by absolute path
mapfile -t ts_files < <(find "$SOURCE_DIR" -type f -name '*.ts' | sort -u)

if [[ ${#ts_files[@]} -eq 0 ]]; then
  echo "No .ts files found in $SOURCE_DIR"
  exit 0
fi

echo "[INFO] Found ${#ts_files[@]} .ts file(s). Converting..."

for input in "${ts_files[@]}"; do
  filename=$(basename "$input")
  output_name="${filename%.ts}.mp4"
  output_path="$DEST_DIR/$output_name"

  echo "[INFO] Converting: $input → $output_path"
  ffmpeg -y -i "$input" -c copy "$output_path"
done

echo "[INFO] Conversion complete. Output saved in: $DEST_DIR"

