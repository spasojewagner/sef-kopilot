# 37. Motion with its end first: an animation that hides nothing

The home page's example of a report tells a story as the page opens: an error, an explanation,
a repair, a verdict. The rule that keeps it safe is that **the element's own style is the end
of the story**; the animation only plays the way there.

```css
.story-valid { }                                  /* the end: the verdict shows       */
.story-invalid { opacity: 0; }                    /* the end: the old verdict is gone */

@media (prefers-reduced-motion: no-preference) {  /* motion only for those who allow it */
  .story-valid   { animation: story-appear 0.35s 3s both; }
  .story-invalid { animation: story-invalid 3.3s both; }
}
@keyframes story-appear { from { opacity: 0; } }  /* no `to`: it ends at the element's style */
```

**Why the end comes first.** Without the media query's permission, or before any animation
runs (a screenshot, a crawler, a print, a browser that skips them), the page shows the whole
story at once, and nothing is left invisible. Written the other way round, with the first frame
as the style and the animation revealing the rest, a visitor who asks for less motion would see
an empty card.

**`animation-fill-mode: both`** (the `both` above) does two things: during the delay it
applies the first keyframe (`backwards`), so the verdict is hidden for its three seconds rather
than flashing in and out; after the end it keeps the last (`forwards`), which here is the
element's own style anyway. A keyframe list with only `from`, or with offsets that stop short of
100 %, animates to that own style, so the end is written once.

**What moves.** Opacity and transforms are drawn by the compositor, without laying the page
out again; a colour or a background, as the replaced value's turns from red to grey, repaints
only its own box. Nothing changes size, so nothing below the example moves while it plays:
hidden steps keep their place.

**What a screen reader hears.** Two verdicts in the same place, one fading out, would be read
together. The drawing is `aria-hidden`, and the figure is named by its caption, one sentence
that tells the same story (`aria-labelledby` on the `figure`).
