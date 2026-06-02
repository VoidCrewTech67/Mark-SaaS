import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

export function formatNumber(n) {
  if (n == null) return "0";
  return n.toLocaleString();
}

export function formatDuration(s) {
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  return `${s.toFixed(2)}s`;
}

export function getFileExtension(name = "") {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

export function stemName(name = "") {
  const parts = name.split(".");
  if (parts.length > 1) parts.pop();
  return parts.join(".");
}
