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
  const { theme, resolvedTheme, setTheme } = useTheme();

  const current: ThemeValue =
    theme === "light" || theme === "dark" ? theme : "system";

  return (
    <div className="space-y-3">
      <Tabs
        value={current}
        onValueChange={(next) => {
          setTheme(toThemeValue(next));
        }}
      >
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="light">Light</TabsTrigger>
          <TabsTrigger value="dark">Dark</TabsTrigger>
        </TabsList>
      </Tabs>

      <p className="text-xs text-muted-foreground">
        Resolved theme: {resolvedTheme ?? current}
      </p>
    </div>
  );
}

