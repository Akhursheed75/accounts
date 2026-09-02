"use client";

import { usePathname } from "next/navigation";

import { AppShell } from "./shell";

/** Every page except the sign-in screen is wrapped in the application shell.
 *  Doing it here rather than with a route group keeps every route a plain path,
 *  so nothing in the build output or the served URLs contains parentheses. */
const BARE_ROUTES = ["/login"];
const BARE_EXACT = ["/"];

export function ConditionalShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (
    BARE_EXACT.includes(pathname) ||
    BARE_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`))
  ) {
    return <>{children}</>;
  }
  return <AppShell>{children}</AppShell>;
}
