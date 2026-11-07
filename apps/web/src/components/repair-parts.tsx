"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { useSession } from "@/hooks/use-session";
import type { ListedRepair, RepairStatus } from "@/lib/repairs";

/** Where a repair stands: one waiting for a person stands out. */
export function RepairStatusBadge({ status }: { status: RepairStatus }) {
  const t = useTranslations("repairs.states");
  return (
    <Badge variant={status === "proposed" ? "warning" : "outline"}>
      {t(status)}
    </Badge>
  );
}

/**
 * A member of the organization, as the visitor says it: they, another member, or a former one,
 * whose account is gone (the API keeps no one's id after that).
 */
export function usePerson(): (userId: string | null) => string {
  const t = useTranslations("repairs.who");
  const session = useSession();
  const me = session.status === "signed-in" ? session.identity.user.id : null;
  return (userId) =>
    userId === null ? t("former") : userId === me ? t("you") : t("member");
}

/**
 * Who proposed a repair: a person, or an API key; and the language model, when it wrote the
 * patches.
 */
export function useProposer(): (
  repair: Pick<ListedRepair, "proposed_by" | "proposed_with_key" | "model">,
) => string {
  const t = useTranslations("repairs");
  const person = usePerson();
  return (repair) => {
    const who = repair.proposed_with_key
      ? t("who.key")
      : person(repair.proposed_by);
    return repair.model ? t("withModel", { who, model: repair.model }) : who;
  };
}
