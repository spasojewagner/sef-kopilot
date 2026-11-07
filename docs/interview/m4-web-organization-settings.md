# M4 — `feat/web-organization-settings`

## Three questions a senior engineer would ask

**1. "Why does the page ask twice only for some changes?"**

Because only some changes delete. A period where there was none, or a shorter one, leaves
invoices behind it that the next deletion takes for good; a longer period, or none, deletes
nothing. A confirmation that appears for every change teaches people to press through it, so it
appears only when it means something, and it says what: the day up to which stored invoices go,
now less the period, written as a day in Belgrade.

**2. "The form is for owners. What if the visitor's role changed after they signed in?"**

The page does not trust the role in the token: it shows the role `GET /auth/me` reports, and
the API decides anyway, since the change checks the role again under the organization's lock.
If the API refuses, the page says that the visitor is no longer the owner and reads their role
again, and the form gives way to the line that says who sets the period.

**3. "What does the page do when the change's answer never comes?"**

It cannot know whether the period changed, so it does not send the change again: it reads the
organization again, shows the period it has, and asks the visitor to check it before trying
again. A server's failure that may have come after the change is treated the same way. The
decision on a repair works so too (ADR-0032).

## The one concept to explain unaided

**Confirm what cannot be undone, and say what will happen**: a confirmation that names its
consequence, here a day, is read; one that asks "are you sure?" about everything is not.

## Supporting facts worth remembering

- The periods offered: a month, three months, half a year, one, two, five and ten years, the
  period the organization has if it is another, and none.
- The phone's header shows the way to the organization as an icon, named for a screen reader
  by the word a wider screen shows.
- The date is computed in the browser from its clock; the API decides what is deleted.
