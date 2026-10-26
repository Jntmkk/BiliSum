// Metro 配置：默认即可，@sentry/react-native/expo 插件会自动 sourcemap 上传。
// 此文件存在是为了让 Sentry 的 Expo 插件识别项目根（无自定义需求）。
const { getDefaultConfig } = require('expo/metro-config');

module.exports = getDefaultConfig(__dirname);
