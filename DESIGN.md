# Design System — Revenue Recovery Agent

> **The constitution:** *Every rupee traces to a rule you can read.*
>
> Every decision in this file answers to that sentence. If a change makes the
> mechanism harder to read, it is wrong, however pretty it looks.

---

## Product Context

- **What this is:** A Streamlit dashboard for an agent that detects failed
  payments, diagnoses each one, and picks a recovery tier from an explainable
  seven-rule table. Stopping rules can refuse to act, and log which rule refused.
- **Who it's for:** Hackathon judges first, for three minutes, on a projector in
  a bright room. Collections ops staff second, for a working day.
- **Space:** Indian fintech, payments, dunning and collections.
- **Project type:** Data-dense internal dashboard. Not a marketing site.
- **Peers:** [razorpay.com](https://razorpay.com), [growfin.ai](https://www.growfin.ai),
  [churnkey.co](https://churnkey.co/feature/payment-recovery)

---

## Aesthetic Direction

- **Direction:** Forensic Ledger. Industrial/utilitarian crossed with editorial.
- **Decoration level:** Minimal. Typography and one saturated colour do all the work.
- **Mood:** A document that proves something, not a dashboard that sells
  something. Calm, exact, unhurried. Closer to an audited statement than to a
  SaaS product tour.

### What the research found

Every product in this category is light mode with a blue primary and one
saturated green for money. Razorpay itself is white page, Inter, `#305EFF`,
navy `#192839`. Growfin is white, Inter, `#1F6FFF`, slate `#475569`. Churnkey is
light with warm greys, a serif headline, green `#28A671`.

They also all make the number huge and the mechanism invisible. Churnkey sells
"optimized by ML models" as a feature, with the black box as the pitch. This
product's competitive claim is the exact inverse, so the design inverts it too.

---

## Typography

Three faces, three jobs. Serif argues. Sans explains. Mono is evidence.

| Role | Face | Why |
|---|---|---|
| **Display / headings / money figure** | **Fraunces** 600 | A serif on an audited figure reads as statement, not startup metric. Every competitor sets numbers in sans. This is the loudest differentiator in the system. Variable optical sizing keeps it sharp at 44px+ and readable at 18px. |
| **Body / UI / every reason string** | **Source Sans 3** 400/600 | A real text face with large apertures, so it survives projector distance. Carries the reason strings, which are the actual product. Not Inter. |
| **Data / ids / amounts / rule statements** | **IBM Plex Mono** 400/500 | Anything a judge might read back to you aloud is set in mono with tabular figures, so columns of rupees align on the decimal. |

**Loading** (Streamlit resolves these from Google Fonts at startup):

```
Fraunces        https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&display=swap
Source Sans 3   https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap
IBM Plex Mono   https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap
```

### Scale

| Token | Value | Use |
|---|---|---|
| `baseFontSize` | `16` | Body, and every reason string |
| `codeFontSize` | `19px` | **Rule statements.** Larger than body and equal to h3. |
| h1 | `44px` / 600 | The money figure. One per page. |
| h2 | `24px` / 600 | Section opener |
| h3 | `18px` / 600 | Sub-section |
| h4–h6 | `16 / 14 / 13px` | Rarely needed |

**Reason strings are body text at full weight and full colour. They are never
caption-grey, never 13px, never `grayColor`.** This is the single most important
typographic rule in the system, and it is the whole inversion expressed in one line.

---

## Color

**Approach:** Restrained. One saturated colour carries meaning; everything else
is ink on warm paper. There is no blue in this product.

| Role | Hex | On page | On card | Notes |
|---|---|---|---|---|
| Page | `#FAF8F3` | — | — | Warm paper, not cool slate |
| Surface | `#FFFFFF` | — | — | Cards, tables, widgets |
| Rule surface | `#FFFFFF` | — | — | `codeBackgroundColor`. White on the warm page, so a rule reads as paper. A warmer chip (`#F3F0E8`) was tried and rejected: it drops green to 4.40:1. |
| Text (ink) | `#14181F` | 16.77:1 | 17.79:1 | |
| Muted | `#5B6470` | 5.65:1 | 6.00:1 | Timestamps, metadata only |
| Primary / buttons | `#1B2430` | 14.75:1 | 15.65:1 | Buttons are ink |
| **Money green** | `#15803D` | 4.73:1 | 5.02:1 | Recovered rupees, nothing else |
| Lost red | `#B91C1C` | 6.10:1 | 6.47:1 | Revenue lost, failed sends |
| Blocked amber | `#B45309` | 4.73:1 | 5.02:1 | A stopping rule refused |
| Border | `#8A8578` | 3.47:1 | 3.68:1 | Control boundaries, WCAG 1.4.11 |

Chart series, deliberately with no green in the sequence, because green labels
money and must never label a category:
`#1B2430` `#6D28D9` `#0E7490` `#B45309` `#B91C1C` `#475569` `#831843`

### The colour law

- **Green means rupees that actually came back.** Never a button. Never a generic
  success state. Never a chart series that is not money.
- **Red is revenue lost** or a send that failed.
- **Amber is a stopping rule that refused to act.**
- **Everything else is ink**, including every button.

Because green and red carry meaning, every place they appear also carries a word
or an icon. Colour is never the only signal.

### Contrast is a test, not a guideline

Every value above is checked against **both** surfaces it sits on by
`test_agent.py`. Text clears 4.5:1 (WCAG AA); control borders and chart series
clear 3:1 (WCAG 1.4.11). Tightest margin in the system is +0.23. If you change a
colour, run the suite.

Two competing palettes were rejected on measurement, not taste. A warm ground of
`#F6F1E8` drops muted text to 4.48:1 and green to 4.42:1. A ground of `#EDE7D9`
with border `#D6CDB8` puts that border at 1.28:1. The ground was lightened to
`#FAF8F3` until every semantic colour cleared its bar.

### Dark mode

**Light is the design. Dark is a fallback**, and the app ships light. If a dark
variant is ever needed, redesign the surfaces rather than inverting: page
`#14181F`, surface `#1C222B`, text `#F2EFE9`, muted `#9AA3AF`, and lift the
semantic colours to `#4ADE80` / `#F87171` / `#FBBF24` so they hold on a dark
ground. Re-run the contrast tests against the new surfaces.

---

## Spacing

- **Base unit:** 8px
- **Density:** 6/10. Dense enough to read as credible ops software, open enough
  that the hero survives a projector.
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48) 3xl(64)

---

## Layout

- **Approach:** Grid-disciplined. Single column, `layout="centered"`, read top to
  bottom in the order the demo is performed.
- **Hero:** The rule and the money figure are **co-equal**. The rule sits in a
  paper chip at 19px mono; the figure sits at 44px serif. Roughly equal ink on
  the page. Neither wins.
- **Max content width:** Streamlit centered default.
- **Border radius:** `4px` everywhere. Ledgers have corners; apps have pills.
- **Never:** three equal columns, centred body text, cards inside cards,
  shadows used to signal premium.

---

## Motion

- **Approach:** Minimal-functional. Streamlit offers almost none natively and
  this system does not pretend otherwise.
- Only transitions that aid comprehension: `st.toast` on an outcome change,
  `st.rerun` after the number moves.
- No scroll reveals, no entrance animations, no GSAP. Nothing on this page should
  move unless a rupee moved.

---

## Streamlit Implementation Notes

This design system is expressed almost entirely through `.streamlit/config.toml`.
**No CSS injection.** Every element stays native so the page stays consistent
when the theme changes.

### The rule mechanism

`codeFontSize` is an independent theme key, separate from `baseFontSize` and
`headingFontSizes` (verified on Streamlit 1.62.0). This is what makes the
inversion buildable natively:

- **Rule statements render through `st.code(rule_text, language=None, wrap_lines=True)`.**
  That single call gets 19px IBM Plex Mono, its own paper-white chip on the warm
  ground, and a **copy button, free, on every rule.** A judge can lift your
  reasoning straight off the projector. The thesis becomes a physical affordance.

### Consequence: inline backticks are banned in caption text

Because `codeFontSize` is 19px, an inline backtick inside a 13px caption renders
at 19px and breaks the line. So:

- `st.code()` blocks are **reserved for rule statements.**
- Identifiers mentioned in captions and body prose are set in **bold**, not
  backticks.
- This requires edits to `dashboard.py`, which currently uses inline backticks in
  several captions.

### Refusals render at full size

A blocked intervention is never greyed out, never collapsed behind an expander,
never shown as an empty state. A refusal is a rule speaking, and the stopping
rules are the most unusual thing in this product. `intervention_skipped` rows get
the same weight as `payment_recovered` rows.

### Theme restart

`.streamlit/config.toml` loads only at startup. Restart Streamlit after editing it.

---

## Anti-Patterns

- Green as a button, a link, or a non-money chart series
- Blue anywhere
- Reason strings set as captions, in `grayColor`, or below 16px
- Inline backticks in caption text (see above)
- CSS injection via `st.markdown(unsafe_allow_html=True)`
- Three-column icon grids, centred everything, decorative gradients
- Emoji used as icons (Streamlit's `:material/*` icons only)
- Dark mode as the default
- Colour used as the only signal for an outcome

---

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-24 | Design system created by `/design-consultation` | Full consultation: competitive research, three independent design voices, contrast verification |
| 2026-08-24 | Light mode confirmed as correct | Razorpay, Growfin and Churnkey are all light; the venue is a projector in a bright room |
| 2026-08-24 | `design-system/revenue-recovery-agent/MASTER.md` superseded | Generic template specifying dark mode, Fira Code, green buttons and a Contact Sales marketing page. Contradicted the shipping theme on every axis. |
| 2026-08-24 | Rule and money figure made co-equal in the hero | Softened from "rule outranks number" to protect the tested beats in `DEMO_SCRIPT.md` |
| 2026-08-24 | One meaning colour kept, rubric red declined | A second meaning colour would dilute the discipline that makes green legible |
| 2026-08-24 | Source Sans 3 chosen over Public Sans for body | Larger apertures, more forgiving at projector distance |
| 2026-08-24 | Warm ground lightened to `#FAF8F3` | `#F6F1E8` and `#EDE7D9` both failed the contrast bar the test suite enforces |
| 2026-08-24 | Border radius set to 4px | Agent default, not explicitly confirmed. Coheres with the ledger direction. |
