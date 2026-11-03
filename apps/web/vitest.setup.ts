// Registers the jest-dom matchers (toBeInTheDocument, toHaveAttribute, ...) with Vitest's
// `expect`, and unmounts rendered trees between tests so they cannot leak into each other.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
