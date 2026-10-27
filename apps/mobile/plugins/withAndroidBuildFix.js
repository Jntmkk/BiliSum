// Expo config plugin: Android build fixes for Expo SDK 58 + RN 0.88
// on machines where android-37 platform is not yet available.
//
// Applied automatically by `npx expo prebuild --platform android`.
// Remove this plugin once Google releases API 37 platform.

// Resolve @expo/config-plugins from expo package (pnpm-safe)
const {
  withGradleProperties,
  withProjectBuildGradle,
  // eslint-disable-next-line @typescript-eslint/no-require-imports
} = require(require.resolve('@expo/config-plugins', {
  paths: [require.resolve('expo/package.json')],
}));

/** Override Expo/RN defaults to match locally installed SDK components. */
const withSdkOverrides = (config) =>
  withGradleProperties(config, (cfg) => {
    cfg.modResults.push(
      { type: 'comment', value: '' },
      { type: 'comment', value: 'Override Expo defaults to match installed SDK' },
      { type: 'property', key: 'android.ndkVersion', value: '27.1.12297006' },
      { type: 'property', key: 'android.compileSdkVersion', value: '36' },
      { type: 'property', key: 'android.targetSdkVersion', value: '36' },
      { type: 'property', key: 'android.suppressUnsupportedCompileSdk', value: '37' },
    );
    return cfg;
  });

/**
 * Disable the AAR metadata version check.
 * Expo SDK 58 AARs declare minCompileSdk=37 but android-37 is not released.
 * The check runs as a Worker so doFirst/doLast can't swallow the failure;
 * disabling the task + pre-creating output dirs for downstream BundleAar
 * is the only reliable workaround.
 */
const withAarMetadataFix = (config) =>
  withProjectBuildGradle(config, (cfg) => {
    cfg.modResults.contents += `

// --- expo-config-plugin:withAndroidBuildFix ---
// TODO: remove after android-37 platform is released
// Expo SDK 58 AARs declare minCompileSdk=37 but android-37 is not released yet.
// Disable the check task and pre-create output dirs for downstream BundleAar.
allprojects {
    tasks.matching { it.name.startsWith("check") && it.name.endsWith("AarMetadata") }.all {
        it.enabled = false
    }
    tasks.matching { it.name.startsWith("bundle") && it.name.endsWith("Aar") }.all {
        it.doFirst {
            def checkTask = project.tasks.findByName(it.name.replace("bundle", "check").replace("Aar", "AarMetadata"))
            if (checkTask) {
                checkTask.outputs.files.files.each { f -> f.mkdirs() }
            }
        }
    }
}
// --- end expo-config-plugin:withAndroidBuildFix ---
`;
    return cfg;
  });

module.exports = (config) => withAarMetadataFix(withSdkOverrides(config));
