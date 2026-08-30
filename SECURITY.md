# Security

## Supported use

RevEng is a local development tool. The default server address is `127.0.0.1`, and the application does not provide authentication, authorization between human users, TLS termination, or multi-tenant isolation.

Do not bind RevEng to a public or shared network interface unless it is placed behind an independently configured authenticated reverse proxy and you have reviewed its filesystem access policy.

## Sensitive local data

The following can contain secrets, source excerpts, local paths, or personal project names and must remain uncommitted:

- `.env`
- `*.db`, `*.sqlite`, and `*.sqlite3`
- generated analysis output directories
- runtime-published capability package artifacts
- test workspaces
- runtime agent-environment asset copies

The repository `.gitignore` excludes these paths. Treat copied logs and screenshots as sensitive until reviewed separately.

## Provider requests

Static analysis does not require network access. Model-assisted workflows send selected analysis context to the provider configured by the user. Review the provider endpoint and the selected files before enabling those workflows.

## Reporting a vulnerability

Use GitHub private vulnerability reporting if it is enabled for the repository. Do not include API keys, private source code, databases, or unredacted local paths in a public issue.
