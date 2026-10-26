#!/bin/zsh
# 把本地最新 Metro bundle 热部署到阿里云 bilisum 容器（无需重启，Expo Go 下次进 App 生效）。
# 用法：pnpm --dir apps/mobile run deploy:bundle
set -euo pipefail

SERVER=${DEPLOY_SERVER:-coder@120.26.16.8}
CONTAINER=${DEPLOY_CONTAINER:-bilisum}
STATIC_DIR=/app/apps/web/static

cd "$(dirname "$0")/.."

OUT=$(mktemp -d /tmp/bilisum-export.XXXXXX)
trap 'rm -rf "$OUT" /tmp/bilisum-bundle.tar.gz' EXIT

echo "› exporting iOS bundle…"
npx expo export --platform ios --output-dir "$OUT" --no-minify > /dev/null
BUNDLE=$(ls "$OUT"/_expo/static/js/ios/*.hbc)
TARBALL=/tmp/bilisum-bundle.tar.gz
tar czf "$TARBALL" -C "$OUT" _expo

echo "› uploading $(basename "$BUNDLE") → $SERVER…"
cat "$TARBALL" | ssh -o BatchMode=yes "$SERVER" 'cat > /tmp/bilisum-bundle.tar.gz'

echo "› extracting into container $CONTAINER…"
ssh -o BatchMode=yes "$SERVER" "docker cp /tmp/bilisum-bundle.tar.gz $CONTAINER:/tmp/ && docker exec $CONTAINER sh -c 'tar xzf /tmp/bilisum-bundle.tar.gz -C $STATIC_DIR && rm /tmp/bilisum-bundle.tar.gz' && rm /tmp/bilisum-bundle.tar.gz"

BASE=$(basename "$BUNDLE")
echo "› verifying http://120.26.16.8:4000/static/_expo/static/js/ios/$BASE"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://120.26.16.8:4000/static/_expo/static/js/ios/$BASE")
if [[ "$CODE" != "200" ]]; then
  echo "✗ deploy failed (bundle http $CODE)" >&2
  exit 1
fi
echo "✓ hot-deployed: http://120.26.16.8:4000/static/_expo/static/js/ios/$BASE"
