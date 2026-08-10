# Möbius Recovery interface

## Visual world

Recovery inherits Möbius's quiet operational shell: near-black neutral surfaces,
off-white text, a single violet action color, and compact status language. It is
an incident workspace, not a warning-themed emergency console; red is reserved
for actual errors and destructive cancellation.

## Composition

The desktop surface is a fixed-width context rail beside a flexible conversation
workspace. On narrow screens the rail becomes the opening section and the
conversation follows in normal document flow. Borders define regions; shadows
are used only for the active composer and carry both offset and blur.

## Typography

Use the native system UI stack for resilient, zero-request rendering. Use the
native monospace stack only for protocol versions, device codes, and build
identifiers. Headings use restrained negative tracking no tighter than -0.025em.

## Color tokens

- Canvas: `#0c0c0e`
- Rail: `#131316`
- Raised surface: `#1a1a1f`
- Primary text: `#f3f1f7`
- Secondary text: `#b9b4c2`
- Border: `#34313a`
- Violet action: `#9177ff`
- Success: `#55c995`
- Danger: `#ff7b82`

## Interaction

Controls have explicit hover, focus, disabled, loading, success, and error
states. Streaming output appears in place without entrance choreography. The
single authored motion is the target-status pulse while a session is connecting;
it is disabled under `prefers-reduced-motion`.

Finish freezes the incident workspace immediately. A managed live target is
shown as closed only after its signed session revocation is confirmed; failure
copy makes clear that local access remains closed and a fresh launch is needed.

The visible page quietly maintains its ephemeral serverless session. If the
worker restarts after inactivity, any stale authenticated page returns to a
dedicated fresh-launch explanation; it never invites reuse of a consumed code.
