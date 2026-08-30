# Security

## Supported use

RevEng is a local development tool. The default server address is `127.0.0.1`. Its request guard rejects non-loopback clients, non-local Host headers, cross-site browser mutations, and mismatched Origin or Referer headers.

The request guard is not user authentication and does not defend against another process already running as the same operating-system user. RevEng does not provide human-user authorization, TLS termination, or multi-tenant isolation. Do not bind it to a public or shared network interface.

## Authored Python execution

Stored capability code, generated capability modules, and agent-authored workflows are trusted Python, not sandboxed plugins. If executed, they can import modules, access the filesystem, start processes, and use the network with the same privileges as RevEng.

Execution of authored Python is disabled by default. It requires `REVENG_ENABLE_AUTHORED_CODE=1` in the process environment. Enable it only after reviewing the stored source. Removing built-ins from an `exec()` namespace is not treated as a security boundary; meaningful isolation would require a separate restricted process, container, or operating-system sandbox.

Capability permission checks fail closed when no policy is wired. Agent workflows use agent capability grants and tool-file permissions. Trusted built-in analysis runs pass an explicit local policy. Keycards restrict the paths supplied to cooperating RevEng tools; they do not stop trusted or authored Python from using normal operating-system APIs.

## Filesystem browser

The Agent Environment browser is limited to the application working directory, a recent analysis root, and roots already represented by the agent's keycard. Query parameters cannot select an unrelated filesystem root.

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

Parallel capability execution is capped at eight workers per fan-out stage. Provider usage can still incur cost; use `ai_limit` and provider-side budget controls for additional protection.

## Reporting a vulnerability

Use GitHub private vulnerability reporting if it is enabled for the repository. Do not include API keys, private source code, databases, or unredacted local paths in a public issue.
