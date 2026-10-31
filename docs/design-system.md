# Design system

Tokens measured from https://ventriloc.ca/en/ with Playwright on 2026-10-31,
not transcribed from the written style guide. Where the two disagree, the
measurement wins and the disagreement is recorded below, because a guide that
is wrong about its own signature detail will be wrong again.

Reproduce any value here by loading the page and reading `getComputedStyle`.

## Where the written guide is wrong

| Claim in the guide | Measured on the live site |
|---|---|
| "Buttons: sharp **0px** corners — the square edge is deliberate contrast to the rounded cards", called "the signature" | **Every button is `20px`.** No `0px`-radius button exists on the page. The three-radius "sharp → asymmetric → round" system the guide builds its identity on is not what the site does. |
| Page background is Canvas White `#ffffff` | `body` is **`#f5f5f5`** (the guide's "Fog"). White is the *card* colour — 33 elements, the most common surface. |
| Radius system is 0px / `6px 0 0` / 200px | Dominant radius is **`8px` (46 uses)**, then `20px` (20). The asymmetric `6px 0px 0px` is real but rare (7 uses), and `8px 0px 0px 8px` (8 uses) is a shape the guide never mentions. |
| "Sections separated purely by whitespace — **no visible line**" | Hairline borders are used: **`1px solid rgba(32,32,32,0.21)`**, 6 elements. |
| Type scale: 12/13/16/32/40/66 | `h2` is **24px** with `-0.48px` tracking, a step the scale omits entirely. |

Confirmed correct, and these are the ones that matter most:

- **Zero box-shadows on the entire page.** Depth comes only from surface colour. Measured: `shadows: []`.
- **Only two families:** Inter and PolySans. Nothing else loads.
- **Display type is weight 400 at 66px**, line-height 60px (0.909), tracking `-1.32px`. The whisper-weight headline is real and is the strongest single idea in the system.
- **Accent is rationed.** Ember `#ff682c` appears on **3 elements** on a full landing page. That is the discipline to copy.
- `20px` is the dominant gap (13 uses); card padding of 70px/60px is real.

## Tokens

PolySans is proprietary and we do not have a licence. **Inter Tight at weight
400** is the substitute: it holds the tight-tracked, light-weight display look.
Inter carries everything else. Both are on Google Fonts.

```css
:root {
  /* Surfaces, darkest-used to lightest */
  --graphite:   #202020;  /* text, and dark section bands (19 elements use it as bg) */
  --steel:      #4d4d4d;  /* secondary body copy */
  --slate:      #828282;  /* muted, tertiary, inactive */
  --mist:       #e8e8e8;  /* hairline dividers */
  --ash:        #efefef;  /* panel surface */
  --fog:        #f5f5f5;  /* PAGE BACKGROUND — not white */
  --canvas:     #ffffff;  /* CARD surface — the thing that floats on fog */
  --ivory:      #ebe6dd;  /* warm editorial wash */

  /* The two accents. Ember is for punctuation, never a button fill. */
  --ember:      #ff682c;
  --brass:      #816729;

  --hairline:   rgba(32, 32, 32, 0.21);

  --font-display: 'Inter Tight', ui-sans-serif, system-ui, sans-serif;
  --font-body:    'Inter', ui-sans-serif, system-ui, sans-serif;

  /* Measured type scale. Display tracking is ~-0.02em at every size. */
  --text-display:    66px;  --lh-display:    0.91;  --ls-display:    -1.32px;
  --text-heading-lg: 40px;  --lh-heading-lg: 1.20;  --ls-heading-lg: -0.80px;
  --text-heading:    32px;  --lh-heading:    1.19;  --ls-heading:    -0.64px;
  --text-subhead:    24px;  --lh-subhead:    1.00;  --ls-subhead:    -0.48px;
  --text-body:       18px;  --lh-body:       1.25;
  --text-ui:         16px;
  --text-caption:    14px;  --lh-caption:    1.43;
  --text-micro:      12px;  --lh-micro:      1.33;

  --gap:        20px;   /* the dominant unit */
  --card-pad:   40px;
  --card-pad-lg:70px;
  --section:    80px;
  --page-max:   1200px;

  --radius-card:   8px;   /* dominant */
  --radius-widget: 20px;  /* data widgets AND buttons — measured, not 0px */
  --radius-pill:   200px; /* nav containers */
  --radius-cut:    6px 0 0; /* the asymmetric accent, used sparingly */
}
```

## The actual design problem

The aesthetic is the easy half. The hard half is that this engine emits a great
deal at once — entities, query plan, retrieval hits with scores, an
applicability decision with a proof tree, zero or more refusals, answer
sentences with citations, verification drops with reasons, an envelope with
limitations, and a 478-cell fleet grid. Rendering all of it at equal weight is
what makes a page feel like a data dump, and no amount of typography fixes it.

So the rule for this UI is: **one answer per screen, everything else earns its
place by being asked for.**

Three tiers, and the tier decides the surface:

1. **The verdict.** What the engineer asked. One of: the answer sentences, the
   applicability decision, or the refusal. Dark `--graphite` band or white card
   at display size. This is the only thing allowed above the fold.
2. **The grounds.** Why the verdict is what it is — the fired rule and its
   conditions, each citation with its stage and Federal Register reference,
   the limitations. White cards on fog, `--text-body`, collapsed to a summary
   line with a count until opened.
3. **The machinery.** Entities, query plan, retrieval scores, verification
   drops, timings. `--text-caption` in `--slate`, behind a disclosure. Present
   because the proof matters, quiet because nobody reads it first.

Ember is reserved for exactly three things, and nothing else: the refusal code,
the citation underline, and the one number in the blast grid that changed. If
ember appears four times on a screen, something has been promoted that should
not have been.

## Stage is a first-class visual

Contract 1.2.0 requires every citation to show its `document_stage`. That is
not a badge to tuck in a corner — it is the difference between "you must do
this" and "someone has proposed this". The mapping:

| Stage | Treatment |
|---|---|
| `EFFECTIVE` | Graphite text, no ornament. The default, the obligation. |
| `ADOPTED_NOT_YET_EFFECTIVE` | Brass rule above the citation + the effective date stated inline. |
| `PROPOSED` | Ivory `--ivory` wash behind the whole block, "PROPOSED" in brass caps. A proposal must never be able to be mistaken for a requirement at a glance, even cropped in a screenshot. |
| `SUPERSEDED` | Slate text, strikethrough on the AD number, superseding revision named. |

## Rules

- Never bold the display face. Weight 400 at 66px is the entire idea.
- No box-shadows anywhere. Depth is `--canvas` on `--fog`, nothing else.
- `--section` (80px) between sections; if a layout feels crowded, add
  whitespace rather than a divider.
- Every PolySans/Inter-Tight element carries `-0.02em` tracking.
- Ember is never a button fill and never a background.
- One sanctioned deviation from "no chromatic colour beyond ember and brass":
  the three `enums.decision` outcomes keep a colour. The measured site is a
  marketing page with no status to show; this product has a 478-cell fleet
  grid an engineer reads at a glance, and taking the colour out of it would
  cost more than the discipline buys. The triad is pulled down into the
  palette's own earth range rather than dashboard green/red/amber, and
  CANNOT_DETERMINE lands exactly on brass `#816729` — fitting, since it is by
  far the most common outcome here (47 usages against 8 and 3) and honest
  uncertainty is the whole point of the engine. Colour never carries a
  decision alone: `StatusGlyph` puts a shape on it too.
- Nothing else is chromatic. A refusal is ember; a failure is graphite.
