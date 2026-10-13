import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY_SERVER_URL = 'bilisum.serverUrl';
const KEY_ACCESS_TOKEN = 'bilisum.accessToken';

export async function getServerUrl(): Promise<string | null> {
  return AsyncStorage.getItem(KEY_SERVER_URL);
}

export async function saveServerUrl(url: string): Promise<void> {
  await AsyncStorage.setItem(KEY_SERVER_URL, url);
}

export async function getAccessToken(): Promise<string | null> {
  return AsyncStorage.getItem(KEY_ACCESS_TOKEN);
}

export async function saveAccessToken(token: string): Promise<void> {
  await AsyncStorage.setItem(KEY_ACCESS_TOKEN, token);
}
