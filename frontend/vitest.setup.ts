import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// waitFor/findBy* default to 1 s, which is too tight when the whole suite runs in
// parallel on a busy machine. Passing tests still resolve as soon as the UI is ready.
configure({ asyncUtilTimeout: 5000 });
