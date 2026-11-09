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
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { ApiError } from "@/lib/api";
import { formatMoment } from "@/lib/format";
import {
  isModelKey,
  isModelName,
  MODEL_PROVIDERS,
  removeModelKey,
  setModelKey,
  type ModelKeyChange,
  type ModelProvider,
  type Organization,
} from "@/lib/organization";
import { meQuery, organizationQuery } from "@/lib/queries";

/** What an owner last did with the key, and how it went. */
type Change = "set" | "removed";

/**
 * Whose language model writes the organization's explanations and repairs (ADR-0058): the
 * server's, or the provider and model of the organization's own key, which every member sees;
 * and, for an owner, a key to set in place of the one it has, or to remove after a second
 * press. The key is sent once and never shown again: the field forgets it once it is saved.
 */
export function ModelKey({
  organization,
  owner,
}: {
  organization: Organization;
  owner: boolean;
}) {
  const t = useTranslations("organization.modelKey");
  const locale = useLocale();
  const why = useModelKeyErrorMessage();
  const changing = useChangeModelKey();
  const own = organization.model_key ?? null;
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
          {own === null
            ? t("servers")
            : t("own", {
                provider: t(`providers.${own.provider}`),
                model: own.model ?? t("defaultModel"),
                moment: formatMoment(locale, own.set_at),
              })}
        </p>
        {owner ? (
          <ModelKeyForm current={own?.provider ?? null} changing={changing} />
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

type Changing = ReturnType<typeof useChangeModelKey>;

/**
 * An owner's provider, model and key to set, and the removal of the key the organization has,
 * which asks again: without it, the server's model writes, or nothing where the server has none.
 */
function ModelKeyForm({
  current,
  changing,
}: {
  current: ModelProvider | null;
  changing: Changing;
}) {
  const t = useTranslations("organization.modelKey");
  const keyHintId = useId();
  const keyInvalidId = useId();
  const modelHintId = useId();
  const modelInvalidId = useId();
  const [provider, setProvider] = useState<ModelProvider>(current ?? "groq");
  const [model, setModel] = useState("");
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

  const has = current !== null;
  const keyWritten = key.trim() !== "";
  const keyValid = isModelKey(key);
  const modelValid = model.trim() === "" || isModelName(model);
  const valid = keyValid && modelValid;

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) {
      return;
    }
    changing.mutate(
      { provider, model: model.trim() || null, api_key: key },
      // Saved, the key leaves the page: the field does not hold it any longer.
      { onSuccess: () => setKey("") },
    );
  }

  return (
    <div className="grid gap-4">
      <form className="grid gap-4" onSubmit={save}>
        <div className="grid gap-2">
          <Label htmlFor="model-provider">{t("provider")}</Label>
          <NativeSelect
            id="model-provider"
            name="model-provider"
            value={provider}
            disabled={changing.isPending}
            onChange={(event) => {
              setProvider(event.target.value as ModelProvider);
              changing.reset();
            }}
          >
            {MODEL_PROVIDERS.map((name) => (
              <NativeSelectOption key={name} value={name}>
                {t(`providers.${name}`)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="model-name">{t("model")}</Label>
          <Input
            id="model-name"
            name="model-name"
            autoComplete="off"
            spellCheck={false}
            maxLength={200}
            placeholder={t(`defaults.${provider}`)}
            value={model}
            aria-invalid={!modelValid}
            aria-describedby={
              modelValid ? modelHintId : `${modelHintId} ${modelInvalidId}`
            }
            disabled={changing.isPending}
            onChange={(event) => {
              setModel(event.target.value);
              changing.reset();
            }}
          />
          <p id={modelHintId} className="text-muted-foreground">
            {t("modelHint")}
          </p>
          {!modelValid && (
            <p id={modelInvalidId} className="text-destructive">
              {t("errors.invalidModel")}
            </p>
          )}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="model-key">{has ? t("newLabel") : t("label")}</Label>
          <Input
            id="model-key"
            name="model-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            maxLength={400}
            value={key}
            aria-invalid={keyWritten && !keyValid}
            aria-describedby={
              keyWritten && !keyValid
                ? `${keyHintId} ${keyInvalidId}`
                : keyHintId
            }
            disabled={changing.isPending}
            onChange={(event) => {
              setKey(event.target.value);
              changing.reset();
            }}
          />
          <p id={keyHintId} className="text-muted-foreground">
            {t("hint")}
          </p>
          {keyWritten && !keyValid && (
            <p id={keyInvalidId} className="text-destructive">
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
 * Setting a key, or removing it with null, and what the cache learns: which provider and model
 * write for the organization, or that the server's do. A failure whose outcome the page cannot
 * know has the organization read again; a refusal, the visitor's role, which has changed since
 * the page learned it.
 */
function useChangeModelKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (change: ModelKeyChange | null): Promise<Change> => {
      if (change === null) {
        await removeModelKey();
        return "removed";
      }
      const state = await setModelKey(change);
      client.setQueryData(organizationQuery.queryKey, (before) =>
        before === undefined ? before : { ...before, model_key: state },
      );
      return "set";
    },
    onSuccess: (change) => {
      if (change === "removed") {
        client.setQueryData(organizationQuery.queryKey, (before) =>
          before === undefined ? before : { ...before, model_key: null },
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
function useModelKeyErrorMessage(): (error: unknown) => string {
  const t = useTranslations("organization.modelKey.errors");
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
        return t("refused");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      case 503:
        return t("unavailable");
      default:
        return uncertain(error) ? t("uncertain") : t("failed");
    }
  };
}
