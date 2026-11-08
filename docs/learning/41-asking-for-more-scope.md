# Asking for more scope: the step-up

A person allows a client *some* scopes. Later, the client calls a tool that needs one more. The
server can say "no" in two very different ways:

```
tool error, inside HTTP 200            challenge, as HTTP 403
──────────────────────────────         ─────────────────────────────────────────────
{"result": {"isError": true,           WWW-Authenticate: Bearer
  "content": "requires the               error="insufficient_scope",
  permission invoices:submit"}}          resource_metadata="…/oauth-protected-resource/mcp",
                                         scope="invoices:validate invoices:submit"
read by the client's model             read by the client itself
the person is told, at best            the person is asked, on the consent page
```

Only the second makes a client act: it sends its person to the authorization server again with
the scopes named, gets a new token, and repeats the same call. This is the MCP revision's
step-up, built on RFC 6750 §3.1.

Three details decide whether it works:

1. **Answer before the tool runs.** Once the MCP SDK runs a tool, any answer is wrapped in a
   200. So the endpoint reads the JSON-RPC message itself, a batch included, and refuses there.
2. **Name every scope still needed**, the ones the client holds as well as the new one. A client
   need not remember what it was allowed; asking for the new scope alone could cost it the old.
3. **Ask only where asking can help.** If the person's role would not allow the scope, the
   consent page could not grant it either; an endless loop of asking helps no one. That case,
   and an API key's missing permission, stay the tool's error.

And one thing to *not* do: hide the tools a token's scopes do not reach. A client never calls a
tool it was not shown, so it never steps up, and the person is never asked.

The challenge only refuses earlier. The tool still checks the role and the scopes itself, so a
mistake in the endpoint's reading can cost a call, never grant one.
