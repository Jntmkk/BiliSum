#!/bin/zsh
# 导出 iOS/Android bundle 并上传到阿里云，同时更新 manifest。
# 服务器端需要在 /api/app/update 提供 manifest。
# 用法：pnpm --dir apps/mobile run deploy:ota
set -euo pipefail

SERVER=${DEPLOY_SERVER:-coder@120.26.16.8}
CONTAINER=${DEPLOY_CONTAINER:-bilisum}
STATIC_DIR=/app/apps/web/static
VERSION=${1:-$(date +%s)}

cd "$(dirname "$0")/.."

OUT=$(mktemp -d /tmp/bilisum-ota.XXXXXX)
trap 'rm -rf "$OUT" /tmp/bilisum-ota-*.tar.gz' EXIT

echo "› exporting bundles…"
npx expo export --platform ios --platform android --output-dir "$OUT" --no-minify > /dev/null

IOS_BUNDLE=$(ls "$OUT"/_expo/static/js/ios/*.hbc 2>/dev/null || ls "$OUT"/_expo/static/js/ios/*.js)
ANDROID_BUNDLE=$(ls "$OUT"/_expo/static/js/android/*.hbc 2>/dev/null || ls "$OUT"/_expo/static/js/android/*.js)
IOS_NAME=$(basename "$IOS_BUNDLE")
ANDROID_NAME=$(basename "$ANDROID_BUNDLE")

TARBALL=/tmp/bilisum-ota-$VERSION.tar.gz
tar czf "$TARBALL" -C "$OUT" _expo

echo "› uploading bundle v$VERSION → $SERVER…"
cat "$TARBALL" | ssh -o BatchMode=yes "$SERVER" 'cat > /tmp/bilisum-ota.tar.gz'

ssh -o BatchMode=yes "$SERVER" << REMOTE
  docker cp /tmp/bilisum-ota.tar.gz $CONTAINER:/tmp/
  docker exec $CONTAINER sh -c '
    tar xzf /tmp/bilisum-ota.tar.gz -C $STATIC_DIR
    rm /tmp/bilisum-ota.tar.gz

    # 更新 manifest（服务器端需要 /api/app/update 接口读这个文件）
    cat > $STATIC_DIR/ota-manifest.json << EOF
{
  "ios": { "version": "$VERSION", "url": "http://120.26.16.8:4000/static/_expo/static/js/ios/$IOS_NAME" },
  "android": { "version": "$VERSION", "url": "http://120.26.16.8:4000/static/_expo/static/js/android/$ANDROID_NAME" }
}
EOF
  '
  rm /tmp/bilisum-ota.tar.gz
REMOTE

echo "✓ OTA bundle v$VERSION deployed"
echo "  ios:     http://120.26.16.8:4000/static/_expo/static/js/ios/$IOS_NAME"
echo "  android: http://120.26.16.8:4000/static/_expo/static/js/android/$ANDROID_NAME"
