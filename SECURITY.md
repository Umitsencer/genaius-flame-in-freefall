# Security and local use

GeNAIus is a local research prototype. The server binds to `127.0.0.1` and has no user authentication, tenant separation or production deployment hardening. Keep that binding for local demonstrations.

## Credentials

- Keep keys in local `.env` or environment variables. `.env` is ignored by Git.
- Never paste a key into an issue, screenshot, source file or model prompt.
- If a key leaks, revoke it at the provider; removing a Git line alone does not revoke access.
- OpenRouter synthesis sends the submitted question and selected public evidence to external providers. Do not enter confidential data.

## Reporting

Do not open an issue containing live credentials, private records or exploit details against a third party. Use GitHub's private vulnerability reporting if available, or contact the maintainer through the profile linked in the README. Never include a working secret.

## Implemented boundaries

The prototype checks Host/Origin headers, bounds request bodies, restricts static-file paths, validates typed inputs, uses JSON model coefficients instead of pickle, and validates external model output. These controls reduce specific risks; they are not a claim of a complete security audit.
