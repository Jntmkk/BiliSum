import { Platform } from 'react-native';
import hotUpdate from 'react-native-ota-hot-update';
import ReactNativeBlobUtil from 'react-native-blob-util';

import { getServerUrl, getAccessToken } from '@/src/store/settings';

// OTA 热更新：每次启动静默检查一次阿里云服务器上的 bundle 更新。
// 服务器需要在 /api/app/update 返回 { version, url, force? } 格式。
// version 是递增整数，app 本地版本低于服务器版本时下载并重启。

const PLATFORM = Platform.OS === 'ios' ? 'ios' : 'android';

export async function checkForHotUpdate(): Promise<void> {
  try {
    const serverUrl = await getServerUrl();
    if (!serverUrl) return;

    const token = await getAccessToken();
    const currentVersion = await hotUpdate.getCurrentVersion();
    const current = parseInt(currentVersion, 10) || 0;

    const res = await fetch(`${serverUrl}/api/app/update?platform=${PLATFORM}&v=${current}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return;

    const data = await res.json();
    if (!data?.url || !data?.version) return;
    if (parseInt(data.version, 10) <= current) return;

    await hotUpdate.downloadBundleUri(
      ReactNativeBlobUtil,
      data.url,
      parseInt(data.version, 10),
      {
        metadata: {
          releaseNote: data.releaseNote ?? '',
          releasedAt: data.releasedAt ?? '',
        },
        restartAfterInstall: true,
      },
    );
  } catch {
    // OTA 检查失败不阻塞启动，下次再试
  }
}
