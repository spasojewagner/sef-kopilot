import { Closing } from "@/components/landing/closing";
import { Developers } from "@/components/landing/developers";
import { Hero } from "@/components/landing/hero";
import { Route } from "@/components/landing/route";
import { Standards } from "@/components/landing/standards";

/**
 * The product's page: what it does and the way to try it, how an invoice goes through it, the
 * rules it checks against, the same checks for programs, and the invoices to try it on.
 */
export default function HomePage() {
  return (
    <div className="flex flex-1 flex-col">
      <Hero />
      <Route />
      <Standards />
      <Developers />
      <Closing />
    </div>
  );
}
