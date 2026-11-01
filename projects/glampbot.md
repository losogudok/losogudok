[← Profile](../README.md) · [Résumé](../RESUME.md)

# GlampBot: from a guest's message to an application tool

**Prototype · TypeScript / Node.js / OpenAI SDK / LiteLLM / grammY / Prisma**

## The problem

A booking assistant needs current availability and application data. A conversational answer alone cannot check a room or create a booking draft.

## Implemented flow

1. A Telegram message reaches the application with the user's identity.
2. The application sends the conversation and JSON Schema tool definitions to the model.
3. The model requests an application tool.
4. The application executes it and returns a structured tool result.
5. A second model call turns that result into a reply for the guest.

## Tools

| Tool | Application action |
| --- | --- |
| check_availability | Look up rooms for the requested dates. |
| get_glamping_info | Retrieve property information and policies. |
| initiate_booking | Create a booking draft for the selected room and dates. |

Tool implementations and their model-facing definitions are collected in a registry. Database access goes through Prisma. The application supplies the Telegram userId when executing a tool instead of relying on the model to choose the user's identity.

## Scope

This is a prototype demonstrating an LLM-to-application tool loop. Booking drafts are distinct from confirmed or paid reservations. It is not presented as a production booking platform.

## What this demonstrates

Function calling, schema-described tools, application-owned identity, and connecting a conversational interface to existing business functions.
