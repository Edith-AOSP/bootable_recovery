#!/bin/bash
#
# Regenerates the localized recovery status images (installing, erasing, error,
# no_command) with Google Sans Flex instead of Roboto.
#
# The platform build regenerates those five PNGs from tools/image_generator and
# copies them into the recovery ramdisk. They are installed here under
# vendor/edith/recovery/res/images/, which the product lists in
# TARGET_PRIVATE_RES_DIRS so it is copied after the generated files.
#
# Google Sans Flex only covers Latin, so it is passed as the Latin font through
# ImageGenerator's --latin_font; Cyrillic/Greek and every mapped script keep
# Roboto/Noto.
#
# Run inside a configured build environment, after a build has produced the host
# jar and the recovery font dir:
#
#   breakfast klee && m RecoveryImageGenerator
#   bootable/recovery/tools/edith-ui/gen_status_text.sh
#
set -euo pipefail

TOP=$(cd "$(dirname "$0")/../../../.." && pwd)
JAR="$TOP/out/host/linux-x86/framework/RecoveryImageGenerator.jar"
RES_DIR="$TOP/bootable/recovery/tools/recovery_l10n/res"
OUT_DIR="$TOP/vendor/edith/recovery/res/images"
FONT="$TOP/vendor/edithui/fonts/GoogleSansFlex-Regular.ttf"
IMAGE_WIDTH=1070

if [ -z "${OUT:-}" ]; then
  echo "OUT is not set; source build/envsetup.sh and run breakfast first." >&2
  exit 1
fi
for f in "$JAR" "$FONT"; do
  if [ ! -f "$f" ]; then
    echo "missing $f" >&2
    exit 1
  fi
done

FONT_DIR=$(mktemp -d)
trap 'rm -rf "$FONT_DIR"' EXIT
cp "$OUT"/obj/ETC/recovery_font_files_intermediates/* "$FONT_DIR"/
cp "$FONT" "$FONT_DIR/GoogleSansFlex-Regular.ttf"

mkdir -p "$OUT_DIR"
for name in installing installing_security erasing error no_command; do
  target="$OUT_DIR/$(echo "$name" | tr -d '_' | sed 's/$/_text.png/')"
  case "$name" in
    installing) target="$OUT_DIR/installing_text.png" ;;
    installing_security) target="$OUT_DIR/installing_security_text.png" ;;
    erasing) target="$OUT_DIR/erasing_text.png" ;;
    error) target="$OUT_DIR/error_text.png" ;;
    no_command) target="$OUT_DIR/no_command_text.png" ;;
  esac
  java -jar "$JAR" \
    --image_width "$IMAGE_WIDTH" \
    --text_name "recovery_$name" \
    --font_dir "$FONT_DIR" \
    --resource_dir "$RES_DIR" \
    --output_file "$target" \
    --latin_font GoogleSansFlex-Regular \
    --center_alignment
  if command -v zopflipng >/dev/null 2>&1; then
    zopflipng -y --iterations=1 --filters=0 "$target" "$target" >/dev/null
  fi
  echo "wrote ${target#"$TOP"/}"
done
