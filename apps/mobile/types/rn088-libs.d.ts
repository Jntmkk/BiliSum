/**
 * react-native-webview@14 的已发布类型与 RN 0.88 不兼容：`.d.ts` 把 `WebView` 标成
 * `React.FunctionComponent<WebViewProps>`，编译器却解析出一个带不可解析泛型的 class，
 * 导致「不能用作 JSX 组件」。这里按 0.88 的函数组件模型重声明它——只改类型视图，
 * 运行时仍是包里原来的实现。等上游发布适配 0.88 的类型后可删掉本文件。
 *
 * `@react-native-segmented-control/segmented-control@2.5.7` 有同样问题，但它的
 * `export default class` 声明优先级更高、`declare module` 覆盖不掉，所以对它的
 * node_modules 里的 index.d.ts 打了补丁（见该文件底部注释）。
 */
import type * as React from 'react';
import type { HostInstance } from 'react-native';

declare module 'react-native-webview' {
  import type {
    AndroidWebViewProps,
    IOSWebViewProps,
    WindowsWebViewProps,
  } from 'react-native-webview/lib/WebViewTypes';

  export type WebViewProps = IOSWebViewProps & AndroidWebViewProps & WindowsWebViewProps;

  /** ref 句柄 = 宿主元素方法 + WebView 的命令方法 */
  export interface WebViewRef extends HostInstance {
    goBack(): void;
    goForward(): void;
    reload(): void;
    stopLoading(): void;
    injectJavaScript(script: string): void;
    requestFocus?(): void;
    postMessage(message: string): void;
    loadUrl?(url: string): void;
    clearCache?(includeDiskFiles: boolean): void;
    clearFormData?(): void;
  }

  export interface WebViewComponentProps extends WebViewProps {
    ref?: React.Ref<WebViewRef> | undefined;
  }

  export const WebView: React.FunctionComponent<WebViewComponentProps>;
  export default WebView;
}
