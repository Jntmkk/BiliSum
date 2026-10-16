import { useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY_SERVER_URL = 'bilisum.serverUrl';
const KEY_ACCESS_TOKEN = 'bilisum.accessToken';

/**
 * 同步缓存：封面图这类在渲染期就要拼出的 URL 不能等 await。
 * 读取时填充，保存时更新。
 */
let serverUrlCache: string | null = null;

export async function getServerUrl(): Promise<string | null> {
  if (serverUrlCache != null) return serverUrlCache;
  serverUrlCache = await AsyncStorage.getItem(KEY_SERVER_URL);
  return serverUrlCache;
}

export async function saveServerUrl(url: string): Promise<void> {
  serverUrlCache = url;
  await AsyncStorage.setItem(KEY_SERVER_URL, url);
}

/** 已缓存的服务器地址；没读过时为 null */
export function peekServerUrl(): string | null {
  return serverUrlCache;
}

/** 组件里取服务器地址（首次挂载时从存储读一次） */
export function useServerUrl(): string | null {
  const [url, setUrl] = useState<string | null>(serverUrlCache);
  useEffect(() => {
    if (serverUrlCache != null) return;
    void getServerUrl().then(setUrl);
  }, []);
  return url;
}

export async function getAccessToken(): Promise<string | null> {
  return AsyncStorage.getItem(KEY_ACCESS_TOKEN);
}

export async function saveAccessToken(token: string): Promise<void> {
  await AsyncStorage.setItem(KEY_ACCESS_TOKEN, token);
}
