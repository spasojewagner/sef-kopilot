# Searching and paging the invoice list

## Three questions a senior engineer would ask

**1. How does a search preserve tenant and member visibility?**

The count and page both use the same conditions, starting with organization scope and
the submitter restriction where it applies. Search matches any of three columns within
that scope. The search string is bound as a parameter and the pattern characters are
escaped so a literal percent sign matches a percent sign.

**2. Why does moving to the next page leave the total unchanged?**

The cursor's timestamp and ID define where the page starts. The count uses only scope
and filters, so it describes all matching invoices. The list remains live, and a later
request can reflect any invoices added or deleted in the meantime.

**3. Where do the filters and cursors live?**

Shareable filters and page size live in the URL. Each accepted edit keeps the preceding
view in browser history. The in-memory cursor stack uses the active filters and is replaced
when those filters or the page size change.

## The one concept to explain unaided

The common scoped conditions define both the total and the list. The cursor restricts
only the page.
