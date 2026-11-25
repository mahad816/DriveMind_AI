import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The type scale uses custom names (text-body, text-label…). Without telling tailwind-merge they are font sizes,
// it treats them as colours and silently drops a real colour such as text-archive-ink.
const merge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["display", "title", "prose", "passage", "body", "label", "meta"] }],
      rounded: [{ rounded: ["control", "panel"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return merge(clsx(inputs));
}
