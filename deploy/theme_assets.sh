#!/bin/sh
# The purchased theme assets (Rizz panel, eSoft website) are licensed and never in git (.gitignore). This moves them
# from a development machine to a server before building the images.
#   sh deploy/theme_assets.sh pack                    # on a machine that has them: writes theme-assets.tgz
#   sh deploy/theme_assets.sh unpack theme-assets.tgz # on the server, in the repository folder
#   sh deploy/theme_assets.sh check                   # are they in place?
# Keep theme-assets.tgz with the licence files in private storage, never in a public place.
set -eu
cd "$(dirname "$0")/.."
PATHS="backend/static/panel backend/static/website/css backend/static/website/fonts backend/static/website/js backend/static/website/img"

case "${1:-}" in
  pack)
    # product screenshots are ours and in git; everything else under website/img is the theme's
    tar czf theme-assets.tgz --exclude="backend/static/website/img/product" $PATHS
    echo "theme-assets.tgz ($(du -h theme-assets.tgz | cut -f1))"
    ;;
  unpack)
    tar xzf "${2:?theme-assets.tgz path}"
    "$0" check
    ;;
  check)
    for f in backend/static/panel/css/app.min.css backend/static/panel/js/app.js backend/static/website/css/main.css; do
      [ -f "$f" ] || { echo "missing: $f  (run: sh deploy/theme_assets.sh unpack theme-assets.tgz)"; exit 1; }
    done
    echo "theme assets in place"
    ;;
  *) echo "usage: $0 pack | unpack <file> | check"; exit 2 ;;
esac
