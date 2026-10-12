import { useEffect, useState } from 'react';
import { Button, StyleSheet, TextInput } from 'react-native';

import { Text, View } from '@/components/Themed';
import { getServerUrl, saveServerUrl } from '@/src/store/settings';

export default function SettingsScreen() {
  const [serverUrl, setServerUrl] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getServerUrl().then((url) => setServerUrl(url ?? ''));
  }, []);

  async function handleSave() {
    await saveServerUrl(serverUrl.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.label}>服务器地址</Text>
      <TextInput
        style={styles.input}
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
