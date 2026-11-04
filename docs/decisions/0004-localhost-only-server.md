# 0004 Keeping the local web server local

## Context

The owner decided the interface runs only on this computer and photos are never uploaded (#3). The server can read any folder path it is given and copy files, so a web page on another site that the owner happens to open must not be able to drive it, and other computers must not reach it.

## Decision

- Bind to `127.0.0.1` only, never `0.0.0.0`.
- Accept requests only when the `Host` header is `127.0.0.1:<port>` or `localhost:<port>`. This blocks DNS-rebinding pages.
- Every `/api/` request must carry a random token created at start-up and embedded in the page (`X-Token` header, or a query parameter for preview images). Other sites cannot read the page, so they cannot learn the token.
- POST bodies must be JSON and at most 32 MB.
- Previews are served only for files from the current scan, looked up by id, never by a path from the request.
- The page loads nothing from the internet, and a Content Security Policy allows only same-origin resources.
- The output folder must be outside the input folder, and must be empty or a folder this tool wrote before for the same input (`.travelphotos-manifest.json`). The tool never deletes files. When it re-applies an order it renames only the files it copied itself.

## Alternatives

- No token: simpler, but any web page could POST to the port.
- A login: the owner decided no accounts are needed for a single-user local tool.

## Consequences

Opening the page from a bookmark after a restart shows a token error until the page is reloaded from the URL printed at start-up.
