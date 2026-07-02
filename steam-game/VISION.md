# VISION — GALA

Creative bible. This is the *why*. When a mechanic or asset decision is ambiguous, resolve it toward
these pillars.

---

## The pitch

You drive an art piece. A weighty, believable car on a real childhood street that slowly stops being
real — the road keeps going but the world around it dissolves into swirling texture, dense ghost
forests, abandoned towns, and expansive deserts under abstract, dramatic skies. **How you drive
paints it.** Smooth and slow, and the world breathes calm. Push, slide, brake late, and it churns.

Two audiences, one game:
- **Drivers / sim-rig owners** come for a car that *feels incredible* and stay for a world that
  reacts to their inputs like nothing else.
- **Relaxers** come for a meditative, generative, drive-forever experience — no timer, no fail state,
  no pressure.

Both are served by the same core loop. Neither is a "mode" bolted on.

---

## Pillars

1. **The car is the brush.** Every art system is downstream of driving. If a visual isn't driven by
   something the player *did with the car*, question whether it belongs. Motion, weight, slip, and
   effort are the input to the painting — not menus, not sliders.

2. **Telemetry is the paint.** Speed, lateral G, yaw rate, slip angle, throttle/brake, suspension
   travel, RPM, steering torque — these are pigments. They drive color, density, weather, terrain
   morph, and sound. (Data contract in [`ARCHITECTURE.md`](./ARCHITECTURE.md#telemetry-bus).)

3. **The world is the canvas and the frame.** Sky, terrain, weather, and the framing of the 39"
   ultrawide / VR headset are compositional elements. We design shots, not just scenery.

4. **Feel over realism, but feel is *earned* by physics.** This is a fantasy world, but the car obeys
   believable physics so the FFB reads true. Weighty. Sometimes slow, sometimes fast, always in a
   **feedback loop with the environment** — the world can push back on the car (drag through dense
   forest, float across desert, drift on ghost-town ice) and the car pushes back on the world.

5. **Real seed, unreal bloom.** It begins somewhere true — Gala Ave up to Benchley-Weinberger
   Elementary, through Del Cerro, past **the Del Cerro golf-course greens and Lake Murray** — and
   grows outward into the abstract. The realness of the start makes the strangeness land.

6. **No punishment.** No lap times shown as judgment, no crashes that end a run, no death. You can
   always keep driving. Difficulty, if any, is expressive, not gating.

---

## The driving ↔ relaxing duality

Think of a single **intensity** value the world tracks, driven by how hard you're driving (see
[`ARCHITECTURE.md`](./ARCHITECTURE.md#intensity-the-master-mood-value)). Both ends are beautiful:

| Low intensity (relaxing) | High intensity (driving) |
|--------------------------|--------------------------|
| Soft light, slow drift of clouds, pastel palettes | Dramatic contrast, fast weather, saturated churn |
| Sparse, calm scatter; open desert; still water | Dense forest, storm skies, reactive terrain |
| Long sightlines, ambient pads | Tighter framing, rhythmic/percussive audio |

The transition is continuous and smooth — never a hard mode switch. A player can live at either end
or ride the whole range in one drive.

---

## World / biome vocabulary (from the brief)

These are the abstract "movements" the procedural world blooms into. Not a fixed sequence — biomes
are seeded by distance-from-anchor + intensity + player-driving history (see PCG notes in
[`ARCHITECTURE.md`](./ARCHITECTURE.md#procedural-world)).

- **The Neighborhood (real seed):** Gala Ave, Del Cerro streets, the golf-course greens, Lake Murray
  edge, up to Benchley-Weinberger. Recognizable, warm, slightly heightened. The only "real" zone.
- **Swirling textures:** the road as a ribbon through painterly, flowing surfaces — the transition
  layer between real and abstract.
- **Dense forests:** dark, tall, close. The world literally slows the car (drag/weight); FFB gets
  heavier. Ghostly light shafts.
- **Ghost towns:** abandoned, desaturated, uncanny-familiar (echoes of the real neighborhood).
  Low-grip, reflective surfaces; a haunted stillness.
- **Expansive deserts:** vast, bright, near-empty. The car feels fast and light; long meditative
  straights; abstract skies dominate the frame.

Skies are their own character everywhere: **abstract, dramatic, volumetric** — not photoreal weather.

### The golf-course sanctum (special / spiritual / mysterious)

The **Del Cerro golf-course area** is not ordinary scenery. It is a **sacred place** in the world —
the emotional and spiritual center of the seed region, and a landmark the procedural world always
lets you find your way back to. Design intent:

- **Spiritual & still.** Even at high intensity elsewhere, approaching the sanctum calms the world:
  light softens and goes golden/otherworldly, wind and audio hush, the palette shifts toward the
  reverent. It reads as *hallowed ground*, not another biome.
- **Mysterious.** Something is here that isn't explained. Reward exploration with atmosphere, not
  answers — ground fog over the greens, impossible geometry at the edges of sight, a presence.
  Never spell it out; it should feel *meant* but unnamable.
- **A fixed point in a shifting world.** As everything else blooms procedurally, the sanctum is
  a hand-authored, consistent anchor. It is the one place that feels the same every drive — the way
  a childhood place stays fixed in memory while everything around it changes.
- **Rewarded, not required.** You don't have to visit it, but the world quietly draws you toward it;
  arriving should feel like a small pilgrimage.

Treat this as the game's spiritual home. When in doubt about tone for this area, err toward reverent,
quiet, and unexplained.

---

## Tone & references

- **The Lake Murray weirdness** that started this: an AC build of the childhood neighborhood that
  "got so fucking weird" it became the seed of the idea. Preserve that accidental-strange energy —
  the familiar rendered wrong-in-a-beautiful-way.
- Adjacent inspirations (for tone, not to copy): meditative drive experiences, generative/abstract
  art toys, atmospheric "vibe" games. The differentiator is **real sim-grade car feel** married to
  that atmosphere — almost nothing does both.

---

## Non-goals (say no to these)

- Not a racing sim. No AI opponents, no leaderboards as the point (an optional "distance/expression"
  stat is fine).
- Not photoreal. Realism serves *feel*, not visuals; the visuals are deliberately abstract.
- Not a driving-school physics debate. We tune for *believable and great*, not for validated
  slip-curve accuracy.
- Not a walking sim / no on-foot sections in scope.
- No microtransactions, no live-service. A crafted, finished experience.

---

## Working title options

- **GALA** — current pick. The street; a celebration; short, ownable.
- _The Long Way Home_ — leans into the childhood-streets-dissolving angle.
- _Throughline_ / _Brushline_ — leans into car-as-brush.
- _Vection_ — the sensation of self-motion; a nod to VR/sim.

Decision owner is the user; do not spend a session bikeshedding the name. `GALA` until told otherwise.
