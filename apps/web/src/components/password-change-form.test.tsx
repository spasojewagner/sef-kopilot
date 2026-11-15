import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { accessToken, STORAGE_KEY } from "@/lib/session";
import { ALICE, json, keepSession, stubApi } from "@/test/api";
import { asSentIn, renderIn } from "@/test/render";

import { PasswordChangeForm } from "./password-change-form";

const CURRENT = "tangerine window walk";
const NEXT = "orchard lemon sundial";

async function submit(confirm = NEXT) {
  for (const [label, value] of [
    ["Current password", CURRENT],
    ["New password", NEXT],
    ["Confirm new password", confirm],
  ]) {
    fireEvent.change(screen.getByLabelText(label, { exact: true }), {
      target: { value },
    });
  }
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Change password" }));
}

describe("Changing the password", () => {
  it("requires the page script and marks the fields for a password manager", () => {
    const page = asSentIn("en", <PasswordChangeForm />);

    expect(page.querySelector("form")).toHaveAttribute("method", "post");
    expect(page.querySelector('button[type="submit"]')).toBeDisabled();
    expect(page.querySelector('[name="current"]')).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(
      page.querySelectorAll('input[autocomplete="new-password"]'),
    ).toHaveLength(2);
  });

  it("refuses a mismatch before asking the API", async () => {
    keepSession();
    const asked = stubApi(() => json(500, {}));
    renderIn("en", <PasswordChangeForm />);

    await submit("another passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The new passwords do not match.",
    );
    expect(asked).toEqual([]);
  });

  it.each([
    [
      401,
      "invalid e-mail address or password",
      "The current password is wrong.",
    ],
    [429, "rate limit reached", "Too many attempts. Try again in 19 s."],
    [
      422,
      [{ type: "common_password" }],
      "This password is among the most common ones",
    ],
    [
      422,
      [{ type: "personal_password" }],
      "This password holds your address's name",
    ],
    [
      422,
      [{ type: "same_password" }],
      "Choose a password that differs from your current one.",
    ],
  ])("shows the refusal for %i %j", async (status, detail, message) => {
    keepSession();
    const asked = stubApi(() =>
      json(status, { detail }, { "Retry-After": "19" }),
    );
    renderIn("en", <PasswordChangeForm />);

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(asked.filter(({ path }) => path === "/auth/password")).toHaveLength(
      1,
    );
  });

  it("keeps the returned tokens, clears the fields and shows the confirmation", async () => {
    keepSession();
    const asked = stubApi(() =>
      json(200, {
        ...ALICE,
        token_type: "bearer",
        access_token: "access-new",
        expires_in: 900,
        refresh_token: "refresh-new",
        refresh_expires_in: 2_592_000,
      }),
    );
    renderIn("en", <PasswordChangeForm />);

    await submit();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Password changed. Other devices have been signed out.",
    );
    const sent = asked.find(({ path }) => path === "/auth/password");
    expect(sent?.method).toBe("POST");
    expect(sent?.headers.get("Authorization")).toBe("Bearer access-2");
    expect(JSON.parse(String(sent?.body))).toEqual({
      current_password: CURRENT,
      new_password: NEXT,
    });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}")).toMatchObject(
      {
        refreshToken: "refresh-new",
      },
    );
    expect(await accessToken()).toBe("access-new");
    for (const label of [
      "Current password",
      "New password",
      "Confirm new password",
    ]) {
      expect(screen.getByLabelText(label, { exact: true })).toHaveValue("");
    }
  });
});
