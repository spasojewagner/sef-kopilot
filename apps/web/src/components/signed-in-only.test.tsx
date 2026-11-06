import { screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { keepSession } from "@/test/api";
import { MESSAGES, renderIn } from "@/test/render";

import { SignedInOnly } from "./signed-in-only";

describe("What only a signed-in visitor sees", () => {
  it("is shown to a signed-in visitor", () => {
    keepSession();

    renderIn("sr-Latn", <SignedInOnly>the invoices</SignedInOnly>);

    expect(screen.getByText("the invoices")).toBeInTheDocument();
  });

  it("is nothing while the session is not known, as the server renders it", () => {
    keepSession();

    const html = renderToString(
      <NextIntlClientProvider
        locale="sr-Latn"
        messages={MESSAGES["sr-Latn"]}
        timeZone="Europe/Belgrade"
      >
        <SignedInOnly>the invoices</SignedInOnly>
      </NextIntlClientProvider>,
    );

    expect(html).toBe("");
  });

  it("gives way to signing in or registering for anyone else", () => {
    renderIn("sr-Latn", <SignedInOnly>the invoices</SignedInOnly>);

    expect(screen.queryByText("the invoices")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Prijava" })).toHaveAttribute(
      "href",
      "/sr-Latn/sign-in",
    );
    expect(screen.getByRole("link", { name: "Registracija" })).toHaveAttribute(
      "href",
      "/sr-Latn/register",
    );
  });
});
