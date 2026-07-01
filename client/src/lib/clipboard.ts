export function copyToClipboard(value: string) {
  void navigator.clipboard?.writeText(value);
}
