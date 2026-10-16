import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';

import { getAccessToken, getServerUrl, saveAccessToken, saveServerUrl } from '@/src/store/settings';
import { invalidateLibrary } from '@/src/api/libraryStore';
import { Card, Section, Separator } from '@/src/components/Card';
import { Icon } from '@/src/components/Icon';
import { Txt } from '@/src/components/Txt';
import { useTabSwipe } from '@/src/features/tabSwipe';
import { useColors } from '@/src/theme/colors';
import { layout, spacing } from '@/src/theme/layout';
import { radius } from '@/src/theme/radius';

export default function SettingsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const panHandlers = useTabSwipe(2);

  const [serverUrl, setServerUrl] = useState('');
  const [token, setToken] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [reveal, setReveal] = useState(false);

  useEffect(() => {
    (async () => {
      setServerUrl((await getServerUrl()) ?? '');
      setToken((await getAccessToken()) ?? '');
      setHydrated(true);
    })();
  }, []);

  const onSave = useCallback(async () => {
    setSaving(true);
    try {
      await saveServerUrl(serverUrl.trim().replace(/\/+$/, ''));
      await saveAccessToken(token.trim());
      invalidateLibrary();
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  }, [serverUrl, token]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 1800);
    return () => clearTimeout(t);
  }, [saved]);

  return (
    // 关掉了原生 header，安全区自己让开（否则第一张卡片顶到状态栏）
    <KeyboardAvoidingView
      {...panHandlers}
      style={{ flex: 1, backgroundColor: colors.groupedBackground, paddingTop: insets.top }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{ paddingTop: spacing.lg, paddingBottom: spacing.xxl }}
        keyboardShouldPersistTaps="handled">
        <Section title="服务器">
          <Card>
            <View style={{ paddingHorizontal: layout.margin, paddingTop: spacing.md }}>
              <Txt variant="footnote" color="secondary">
                服务器地址
              </Txt>
            </View>
            <Field
              value={serverUrl}
              onChangeText={setServerUrl}
              placeholder="http://192.168.1.10:3838"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />
            <Separator />
            <View style={{ paddingHorizontal: layout.margin, paddingTop: spacing.md }}>
              <Txt variant="footnote" color="secondary">
                访问密钥
              </Txt>
            </View>
            <Field
              value={token}
              onChangeText={setToken}
              placeholder="留空则不发送 Authorization"
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry={!reveal}
              trailing={
                <Pressable onPress={() => setReveal((v) => !v)} hitSlop={8}>
                  <Icon
                    sf={reveal ? 'eye.slash' : 'eye'}
                    ion={reveal ? 'eye-off-outline' : 'eye-outline'}
                    size={18}
                    color={colors.secondaryLabel}
                  />
                </Pressable>
              }
            />
          </Card>
          <Txt
            variant="footnote"
            color="secondary"
            style={{ paddingHorizontal: layout.margin + spacing.xs, marginTop: spacing.sm }}>
            在服务端用 bilisum 生成的访问密钥；留空则不发送 Authorization 头。
          </Txt>
        </Section>

        <View style={{ paddingHorizontal: layout.margin }}>
          <Pressable
            onPress={onSave}
            disabled={saving || !hydrated}
            style={({ pressed }) => ({
              height: 50,
              borderRadius: radius.md,
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'row',
              gap: spacing.sm,
              backgroundColor: saved ? colors.success : colors.accent,
              opacity: saving || !hydrated ? 0.6 : pressed ? 0.8 : 1,
            })}>
            {saving ? <ActivityIndicator size="small" color="#FFFFFF" /> : null}
            <Txt variant="headline" style={{ color: '#FFFFFF' }}>
              {saved ? '已保存' : '保存'}
            </Txt>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({
  trailing,
  ...inputProps
}: React.ComponentProps<typeof TextInput> & { trailing?: React.ReactNode }) {
  const colors = useColors();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        paddingHorizontal: layout.margin,
        paddingBottom: spacing.md,
      }}>
      <TextInput
        {...inputProps}
        placeholderTextColor={colors.tertiaryLabel as string}
        style={{
          flex: 1,
          height: layout.touchTarget,
          fontSize: 17,
          color: colors.label as string,
        }}
      />
      {trailing}
    </View>
  );
}
