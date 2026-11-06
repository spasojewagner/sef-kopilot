// Joins class names and resolves Tailwind conflicts, the last one winning. The components of
// `src/components/ui` import it from `cn` directly, as shadcn/ui's registry writes them; the
// application's own code imports it from here.
export { cn } from "cn";
