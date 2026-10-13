import { useEffect, useState } from 'react';
import { Button, StyleSheet, TextInput, useColorScheme } from 'react-native';

import { Text, View } from '@/components/Themed';
import {
  getAccessToken,
  getServerUrl,
  saveAccessToken,
  saveServerUrl,
} from '@/src/store/settings';

export default function SettingsScreen() {
  const [serverUrl, setServerUrl] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [saved, setSaved] = useState(false);
  const isDark = useColorScheme() === 'dark';

  useEffect(() => {
    getServerUrl().then((url) => setServerUrl(url ?? ''));
    getAccessToken().then((token) => setAccessToken(token ?? ''));
  }, []);

  async function handleSave() {
    await saveServerUrl(serverUrl.trim());
    await saveAccessToken(accessToken.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.label}>服务器地址</Text>
      <TextInput
        style={[styles.input, { color: isDark ? '#eee' : '#222' }]}
        placeholder="http://192.168.1.10:3838"
        placeholderTextColor="#999"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        value={serverUrl}
        onChangeText={setServerUrl}
      />
      <Text style={styles.hint}>
        需要能访问到运行 BiliSum 服务的机器（同一局域网或公网地址）
      </Text>

      <Text style={styles.label}>访问密钥</Text>
      <TextInput
        style={[styles.input, { color: isDark ? '#eee' : '#222' }]}
        placeholder="BiliSum 访问密钥"
        placeholderTextColor="#999"
        autoCapitalize="none"
        autoCorrect={false}
        value={accessToken}
        onChangeText={setAccessToken}
      />
      <Text style={styles.hint}>
        与服务端数据目录下 auth.json 中的 access_token 一致，
        或通过环境变量 VIDEO_SUM_ACCESS_TOKEN 配置
      </Text>

      <Button title={saved ? '已保存 ✓' : '保存'} onPress={handleSave} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
  },
  label: {
    fontSize: 14,
    marginBottom: 8,
    opacity: 0.7,
  },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    marginBottom: 8,
  },
  hint: {
    fontSize: 12,
    opacity: 0.5,
    marginBottom: 16,
  },
});
