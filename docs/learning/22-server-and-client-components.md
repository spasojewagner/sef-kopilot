# 22. Server and client components: what runs where

In the App Router every component is a server component, unless its file starts with
`"use client"`. A server component runs when the page is rendered, here once per language when
the application is built. It sends HTML and a description of the tree, and its code never
reaches the browser. A client component is rendered on the server too, for the first HTML; its
code is then sent to the browser, which brings it to life (hydration). Only then can it hold
state, react to the visitor, read the current address and call the API.

```text
[locale]/layout.tsx            server: reads the language and the messages
└─ NextIntlClientProvider      client: the messages, for the client components below
   └─ QueryProvider            client: the cache of the API's answers
      ├─ SiteHeader            server
      │  └─ LanguageSwitcher   client: needs the current path
      ├─ the page              server: text, rendered at build time
      └─ SiteFooter            server
         └─ ApiStatus          client: asks the API from the visitor's browser
```

**Start on the server; go to the client only where the page needs the browser.** That means
state, effects, the address, or a call to the API from the visitor's side. A client component
cannot import a server one, but it can render one that it is given as `children`, which is how
the two providers wrap server components. What crosses the boundary as props must be
serializable: text, numbers, plain objects, not functions.

**Why the API's status is a client component.** The page is built once and served as static
HTML; the API's answer is the one it gives now. A server component would freeze the answer the
build got into the HTML. As a client component, the static HTML says "Checking the API…", and
the browser asks once the page is alive.

**Why the cache is made differently on each side.** On the server a cache that lives in the
module would be shared by everyone's renders, so each render gets a new one. In the browser one
cache for the whole visit keeps answers from page to page. It lives outside React, because React
throws away the state of a tree that suspends before it is first shown.

**Why the language is a root parameter.** `next/root-params` lets any server component read
`[locale]` without it being passed down, and `generateStaticParams` names both languages, so
both versions of each page are built. The messages reach client components through
`NextIntlClientProvider`; on the server, `getTranslations` reads them directly.

The question to ask of a new component: does it need the browser? If not, it stays on the
server and costs the visitor nothing to download.
