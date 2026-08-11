# AGENTS.md

# IoT Dashboard – Project Instructions

These instructions apply to the entire repository.

## Mission

This project is building a professional, scalable IoT platform for environmental monitoring and property management.

The current Raspberry Pi + ESP32 dashboard is a prototype that will gradually evolve into a production-grade system supporting MQTT, LoRaWAN, multiple sensor and actuator nodes, and eventually a dedicated Linux server.

Always preserve this long-term direction.

---

## Read First

Before making changes, always read:

1. README.md
2. Relevant source files for the requested feature

If additional project documentation exists under `docs/`, read the relevant documents before implementing new features.

---

## Development Philosophy

- Never rebuild the project from scratch.
- Improve the existing architecture incrementally.
- Preserve backwards compatibility whenever practical.
- Make the smallest change necessary to implement a feature.
- Never redesign major components without explicit approval.

---

## Git Workflow

- Always work on a feature branch.
- Explain the implementation plan before writing code.
- Keep commits focused on one feature or fix.
- Never commit directly to `main`.
- Never commit runtime files, databases, virtual environments, or secrets.

---

## Versioning

Use Semantic Versioning.

- Major versions = architectural milestones
- Minor versions = new features
- Patch versions = software bug fixes

Repository maintenance (documentation, CI, AGENTS.md, etc.) does **not** create a new software version.

---

## Coding Guidelines

- Prefer readable code over clever code.
- Keep functions focused and modular.
- Avoid unnecessary dependencies.
- Reuse existing code whenever possible.
- Preserve the existing Flask + SQLite architecture until instructed otherwise.

---

## Database Principles

The normalized database model is a core architectural decision.

Do not redesign or denormalize the schema without approval.

Future features (MQTT, LoRaWAN, actuators, node management) should extend the existing model rather than replace it.

---

## Firmware Principles

Firmware belongs under `firmware/`.

Keep firmware modular and reusable.

Avoid hardcoding anything except simple configuration constants unless instructed otherwise.

---

## Dashboard Principles

The dashboard should remain clean, responsive, and easy to understand.

Prefer incremental improvements over complete UI redesigns.

Do not remove existing functionality while implementing new features.

---

## Documentation

Update `README.md` whenever user-visible functionality changes.

Keep documentation concise and consistent with the current version of the project.

---

## Testing

Whenever practical:

- verify backend functionality
- verify frontend behavior
- preserve existing APIs
- avoid breaking previous functionality

The user performs Raspberry Pi deployment and ESP32 hardware testing.

---

## Deployment

Deployment target:

GitHub
→ Raspberry Pi
→ `git pull`
→ `sudo systemctl restart iot-dashboard`

The Raspberry Pi is the deployment and testing machine, not the primary development environment.

---

## Never Do Without Approval

- Rewrite the project from scratch.
- Replace major technologies (Flask, SQLite, etc.).
- Redesign the database schema.
- Remove backwards compatibility.
- Delete existing features to simplify implementation.
- Introduce breaking API changes.
