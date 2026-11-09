# Security reporting

Deepforge security concerns include the Lua sandbox, untrusted multiplayer
inputs, credential handling and authority over externally controlled actors.
The controller service is a trusted-project local interface rather than a
multi-tenant hosting boundary. Keep it bound to loopback unless a deployment
provides its own reviewed network protections.

Report ordinary bugs through this repository's issue tracker. Include a
version, configuration and minimal reproduction with sensitive data removed.
Use private reporting if the repository offers it for a vulnerability; do not
publish tokens, private world data or operational credentials in an issue.

Security support and platform qualification are version-specific. Preserve
source and binary identities when reporting a suspected issue. Existing
upstream author attributions remain in the source and legal notices.
