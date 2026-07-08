"use client";

import { useTheme } from "next-themes";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type ThemeValue = "system" | "light" | "dark";

function toThemeValue(value: string): ThemeValue {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const current: ThemeValue =
    theme === "light" || theme === "dark" ? theme : "system";

  return (
    <Tabs
      value={current}
      onValueChange={(next) => {
        setTheme(toThemeValue(next));
      }}
      aria-label="Appearance"
    >
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="system">System</TabsTrigger>
        <TabsTrigger value="light">Light</TabsTrigger>
        <TabsTrigger value="dark">Dark</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}
