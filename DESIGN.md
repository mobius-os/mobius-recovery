# Möbius Recovery interface

## Visual world

Recovery is Möbius working on itself from outside, so it wears the shell's own
skin rather than a look of its own: the shell's default dark theme tokens, the
Möbius mark beside the wordmark, Inter, quiet sidebar rows, plain assistant
prose, accent user bubbles, compact activity rows, and the rounded composer
pill. It is an incident workspace, not a warning-themed emergency console; red
is reserved for actual errors and destructive cancellation.

## Composition

The desktop surface is a sidebar (brand, target status, session clock, provider
rows, End recovery) beside a headerless conversation, the same arrangement as
the shell's drawer and chat. On narrow screens the sidebar becomes a compact
opening section with End recovery beside the brand, and the conversation
follows with the composer pinned to the bottom. Hairline borders define
regions; shadows are reserved for dialogs.

## Typography

Inter 400/500/600 for all interface text and JetBrains Mono 400 for commands,
the same latin-subset files and metric-matched fallbacks the shell uses. They
are baked into the image and served from the worker's own origin (`/assets/`),
so the page still makes no request to any other host. Body text is 15px; the
wordmark is 20px semibold; headings stay at 28px or below.

## Color tokens

The shell's default dark theme:

- Background: `#0d0d0d`
- Surface: `#171717`, raised surface `#212121`
- Border: `#2a2a2a`, hairline `#1f1f1f`
- Primary text: `#ececec`
- Secondary text: `#a8a8a8`
- Accent: `#8b6cf7` (hover `#7c5ce6`, wash `rgba(139,108,247,.14)`), white on accent
- Success: `#10b981`
- Warning: `#fbbf24`
- Danger: `#f87171`

## Interaction

Controls have explicit hover, focus, disabled, loading, success, and error
states. Streaming output appears in place without entrance choreography.
Authored motion is limited to the target-status pulse, the activity spinner,
and the working-label sweep; all are disabled under `prefers-reduced-motion`.
The transcript reads like a Möbius chat. Consecutive tool calls collapse into one
activity line worded exactly as the shell words it ("Running a command ·
Reading files" while live, "Ran commands, read a file" once settled), with the
shell's type glyph, and expand to a quiet timeline of raw tool names and what
they ran. Assistant replies render the Markdown subset agents write
(paragraphs, headings, lists, code, bold), built from text nodes only.

Finish freezes the incident workspace immediately. A managed live target is
shown as closed only after its signed session revocation is confirmed; failure
copy makes clear that local access remains closed and a fresh launch is needed.

The visible page quietly maintains its ephemeral serverless session. If the
worker restarts after inactivity, any stale authenticated page returns to a
dedicated fresh-launch explanation; it never invites reuse of a consumed code.
The context rail shows the server-issued idle countdown and explains that
activity renews it only up to the one-hour session maximum. The conversation
shows an elapsed, named activity line before the provider emits its first token.
Its elapsed time comes from the worker's turn coordinator, so revisiting the
page does not restart it. Remote command summaries stay in their actual order
between agent prose; internal build, protocol, and session identifiers stay out
of the operator workspace.
