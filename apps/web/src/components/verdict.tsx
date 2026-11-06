import { CircleAlert, CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";

/** Whether the validator found the invoice valid: no fatal violation, whatever the warnings. */
export function Verdict({ valid }: { valid: boolean }) {
  const t = useTranslations("verdict");
  return valid ? (
    <Badge variant="secondary">
      <CircleCheck />
      {t("valid")}
    </Badge>
  ) : (
    <Badge variant="destructive">
      <CircleAlert />
      {t("invalid")}
    </Badge>
  );
}
