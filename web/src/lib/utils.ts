import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Safely extracts a readable error message from any thrown error value.
 */
export function extractErrorMessage(error: unknown, fallback: string = "操作失败"): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string" && error.trim()) return error.trim();
  if (typeof error === "object" && error !== null && "message" in error) {
    const msg = error.message;
    if (typeof msg === "string" && msg.trim()) return msg.trim();
  }
  return fallback;
}

/**
 * Wraps a promise into a Go-style result tuple [data, error], eliminating the need for try-catch nesting.
 */
export async function to<T, E = Error>(promise: Promise<T>): Promise<[T, null] | [null, E]> {
  try {
    const data = await promise;
    return [data, null];
  } catch (error) {
    return [null, error as E];
  }
}
