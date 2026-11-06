import { describe, expect, it } from "vitest";

import { MESSAGES } from "@/test/render";

import { routing } from "./routing";

/** Every message by its key, ``home.title``, with its text. */
function flatten(messages: object, prefix = ""): Map<string, unknown> {
  const flat = new Map<string, unknown>();
  for (const [key, value] of Object.entries(messages)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object") {
      for (const [inner, text] of flatten(value, path)) {
        flat.set(inner, text);
      }
    } else {
      flat.set(path, value);
    }
  }
  return flat;
}

/** The arguments a message takes, ``{version}``, which every translation must take too. */
function argumentsOf(text: string): string[] {
  return [...text.matchAll(/\{\s*([A-Za-z_]\w*)/g)]
    .map((found) => found[1])
    .sort();
}

describe("Messages", () => {
  const serbian = flatten(MESSAGES["sr-Latn"]);

  it("are there for every language of the routing", () => {
    expect(Object.keys(MESSAGES).sort()).toEqual([...routing.locales].sort());
  });

  it.each(routing.locales)(
    "in %s have the keys the Serbian ones have, each a text",
    (locale) => {
      const messages = flatten(MESSAGES[locale]);

      expect([...messages.keys()].sort()).toEqual([...serbian.keys()].sort());
      for (const [key, text] of messages) {
        expect(typeof text, key).toBe("string");
        expect((text as string).trim(), key).not.toBe("");
        expect(argumentsOf(text as string), key).toEqual(
          argumentsOf(serbian.get(key) as string),
        );
      }
    },
  );
});
