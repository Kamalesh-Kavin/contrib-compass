# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `main` (latest) | Yes |
| Older tags | No — please upgrade |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, email **kamalesh.s7316@gmail.com** with the subject line:

```
[SECURITY] contrib-compass — <brief description>
```

Include as much detail as possible:

- A description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept code
- Affected versions (if known)
- Any suggested mitigations

You will receive an acknowledgement within **48 hours**.  We aim to release a fix or mitigation within **14 days** for critical issues.

## Scope

This project is a web application that:

- Accepts user-uploaded files (PDF, DOCX) — injection via malformed files is in scope
- Calls the GitHub REST API using user-provided tokens — token leakage is in scope
- Renders user-supplied content in HTML templates — XSS is in scope

The following are **out of scope**:

- Vulnerabilities in third-party dependencies (report those upstream)
- Denial-of-service attacks against the free-tier Render deployment
- Issues requiring physical access to the server

## Responsible disclosure

We follow responsible disclosure: we will credit you in the release notes (with your permission) once the vulnerability is fixed.
