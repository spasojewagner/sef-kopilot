"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { formatMoment } from "@/lib/format";
import {
  isSefKey,
  removeSefKey,
  setSefKey,
  type Organization,
} from "@/lib/organization";
import { meQuery, organizationQuery } from "@/lib/queries";

/** What an owner last did with the key, and how it went. */
type Change = "set" | "removed";

/**
 * The organization's key to SEF (ADR-0050): since when it has one, which every member sees, and,
 * for an owner, a key to set in place of the one it has, or to remove after a second press. The
 * key is sent once and never shown again: the field forgets it as soon as it is saved.
 */
export function SefKey({
  organization,
  owner,
}: {
  organization: Organization;
  owner: boolean;
}) {
  const t = useTranslations("organization.sefKey");
  const locale = useLocale();
  const why = useSefKeyErrorMessage();
  const changing = useChangeSefKey();
  const setAt = organization.sef_key_set_at ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <p>
          {setAt === null
            ? t("none")
            : t("set", { moment: formatMoment(locale, setAt) })}
        </p>
        {owner ? (
          <SefKeyForm has={setAt !== null} changing={changing} />
        ) : (
          <p className="text-muted-foreground">{t("ownersOnly")}</p>
        )}
        {changing.isError && (
          <Alert variant="destructive">
            <AlertDescription>{why(changing.error)}</AlertDescription>
          </Alert>
        )}
        {changing.isSuccess && (
          <p role="status">
            {changing.data === "set" ? t("saved") : t("removed")}
          </p>
        )}
        {changing.isPending && (
          <p role="status" className="text-muted-foreground">
            {t("saving")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

type Changing = ReturnType<typeof useChangeSefKey>;

/**
 * An owner's key to set, and the removal of the one the organization has, which asks again: with
 * no key, nothing is sent to SEF for the organization.
 */
function SefKeyForm({ has, changing }: { has: boolean; changing: Changing }) {
  const t = useTranslations("organization.sefKey");
  const hintId = useId();
  const invalidId = useId();
  const [key, setKey] = useState("");
  const [confirming, setConfirming] = useState(false);
  // The button pressed goes away with the question it asked: the keyboard's focus follows to
  // the button that takes its place.
  const confirmation = useRef<HTMLButtonElement>(null);
  const remove = useRef<HTMLButtonElement>(null);
  const focusing = useRef(false);
  useEffect(() => {
    if (focusing.current) {
      (confirming ? confirmation : remove).current?.focus();
      focusing.current = false;
    }
  }, [confirming]);

  const written = key.trim() !== "";
  const valid = isSefKey(key);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) {
      return;
    }
    changing.mutate(key, {
      // Saved, the key leaves the page: the field does not hold it any longer.
      onSuccess: () => setKey(""),
    });
  }

  return (
    <div className="grid gap-4">
      <form className="grid gap-4" onSubmit={save}>
        <div className="grid gap-2">
          <Label htmlFor="sef-key">{has ? t("newLabel") : t("label")}</Label>
          <Input
            id="sef-key"
            name="sef-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            maxLength={400}
            value={key}
            aria-invalid={written && !valid}
            aria-describedby={
              written && !valid ? `${hintId} ${invalidId}` : hintId
            }
            disabled={changing.isPending}
            onChange={(event) => {
              setKey(event.target.value);
              changing.reset();
            }}
          />
          <p id={hintId} className="text-muted-foreground">
            {t("hint")}
          </p>
          {written && !valid && (
            <p id={invalidId} className="text-destructive">
              {t("errors.invalid")}
            </p>
          )}
        </div>
        <div>
          <Button type="submit" disabled={changing.isPending || !valid}>
            {has ? t("replace") : t("save")}
          </Button>
        </div>
      </form>
      {has &&
        (confirming ? (
          <div className="grid gap-3 rounded-lg border p-4">
            <p className="font-medium">{t("confirmRemove")}</p>
            <div className="flex flex-wrap gap-2">
              <Button
                ref={confirmation}
                type="button"
                variant="destructive"
                onClick={() => {
                  setConfirming(false);
                  changing.mutate(null);
                }}
              >
                {t("removeNow")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  focusing.current = true;
                  setConfirming(false);
                }}
              >
                {t("cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <Button
              ref={remove}
              type="button"
              variant="outline"
              disabled={changing.isPending}
              onClick={() => {
                focusing.current = true;
                changing.reset();
                setConfirming(true);
              }}
            >
              {t("remove")}
            </Button>
          </div>
        ))}
    </div>
  );
}

/**
 * Setting a key, or removing it with null, and what the cache learns: since when the
 * organization has a key, or that it has none. A failure whose outcome the page cannot know has
 * the organization read again; a refusal, the visitor's role, which has changed since the page
 * learned it.
 */
function useChangeSefKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (key: string | null): Promise<Change> => {
      if (key === null) {
        await removeSefKey();
        return "removed";
      }
      const state = await setSefKey(key);
      client.setQueryData(organizationQuery.queryKey, (before) =>
        before === undefined
          ? before
          : { ...before, sef_key_set_at: state.set_at },
      );
      return "set";
    },
    onSuccess: (change) => {
      if (change === "removed") {
        client.setQueryData(organizationQuery.queryKey, (before) =>
          before === undefined ? before : { ...before, sef_key_set_at: null },
        );
      }
    },
    onError: (error) => {
      if (uncertain(error)) {
        void client.invalidateQueries({ queryKey: organizationQuery.queryKey });
      } else if (error instanceof ApiError && error.status === 403) {
        void client.invalidateQueries({ queryKey: meQuery.queryKey });
      }
    },
  });
}

/** Whether the key may have changed though the page did not hear of it. */
function uncertain(error: unknown): boolean {
  return !(error instanceof ApiError) || [500, 502, 504].includes(error.status);
}

/** Why the key was not changed, in the visitor's language. */
function useSefKeyErrorMessage(): (error: unknown) => string {
  const t = useTranslations("organization.sefKey.errors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    switch (error.status) {
      case 401:
        return t("signedOut");
      case 403:
        return t("forbidden");
      case 422:
        return t("invalid");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      case 503:
        return t("unavailable");
      default:
        return uncertain(error) ? t("uncertain") : t("failed");
    }
  };
}
