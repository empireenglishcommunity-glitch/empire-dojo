# Recording brief — the 11 scenes that close the film reservations

**This is the only outstanding item in the programme that software cannot finish.**
Everything around it is already built and tested: drop the files in, list them in
one manifest, and the coverage ledger stops printing the caveat by itself.

---

## Why these 11 scenes

Two CEFR descriptors name **films**:

| descriptor | what it says |
|---|---|
| `B2.R.2` | *"…most TV news and current-affairs programmes and **the majority of films** in standard dialect"* |
| `C1.R.2` | *"follow **films** employing a considerable degree of slang and idiomatic usage"* |

Our audio is Kokoro TTS. It delivers the words, the slang, the contractions and
the ellipsis faithfully — but **one clean voice per turn, no overlapping speech,
no regional accent, and no emotional prosody.** In a real film, whether a line is
a joke, a threat or a kindness is carried by *how it is said*. A student who
understands every one of our synthesised scenes has still never had to read tone
off a real voice.

So both descriptors are marked **taught, with a stated reservation** — honest, and
printed next to the word "OK" on every ledger run. Real recordings are the only
thing that closes them.

**Nothing is broken and no student is blocked.** The scenes are fully playable and
fully assessable today. This is about the strength of one specific claim.

---

## What to record

Eleven scenes. Each is a short two- or three-person conversation, **1½–2 minutes**
of speech. Full scripts, with every line and speaker label, are on the live site
at `/content-review/b2.html` and `/content-review/c1.html` (behind your ops
passcode), or in the repo at
`empire-nexus/bots/discord-learning-bot/content/{b2,c1}/broadcast/`.

| file to produce | scene | voices needed | turns | length |
|---|---|---|---|---|
| `b2-w3-scene.mp3` | The Photograph | 2 — Mona, Tarek | 17 | ~1:40 |
| `b2-w5-scene.mp3` | We Should Have Said Something | 2 — Layla, Sami | 15 | ~1:35 |
| `b2-w7-scene.mp3` | I Wish You'd Told Me | 2 — Hana, Father | 12 | ~1:20 |
| `b2-w15-scene.mp3` | It Was You Who Called Them | 3 — Samira, Karim, Nour | 20 | ~1:37 |
| `b2-w16-scene.mp3` | Off the Record | 2 — Interviewer, Ms Farid | 14 | ~1:39 |
| `c1-w2-scene.mp3` | You Said You'd Binned It | 2 — Mona, Tarek | 13 | ~1:43 |
| `c1-w7-scene.mp3` | Is That an Order or Not | 2 — Nour, Sami | 18 | ~1:50 |
| `c1-w11-scene.mp3` | So Did We Agree or Not | 3 — Rania, Tarek, Hala | 27 | ~1:45 |
| `c1-w14-scene.mp3` | On Paper It's Fine | 2 — Dalia, Fouad | 17 | ~1:47 |
| `c1-w15-scene.mp3` | Let's Not Open That | 2 — Hala, Fouad | 16 | ~1:48 |
| `c1-w16-scene.mp3` | Is That Thing Off | 2 — Interviewer, Ms Farid | 18 | ~1:48 |

**Total: about 19 minutes of finished audio.** Realistically 4–6 speakers can cover
all eleven, since characters repeat across scenes.

### How to perform them — this is the part that matters

The whole value is in what synthesis cannot do. Please ask the speakers to:

- **Overlap and interrupt.** Several scripts are written to be cut into (`—` marks
  an interruption). Let the speakers genuinely talk over each other.
- **Play the subtext, not the words.** These scenes are built so the meaning sits
  under the line. In `Off the Record`, "It's a much worse answer, which is exactly
  why you got the other one" should land as weary self-awareness, not as
  information.
- **Leave the pauses in.** The `...` marks are real hesitations. They carry as much
  as the words do.
- **Use natural, unpolished delivery.** Not newsreader English. Ordinary people
  having a difficult conversation.
- **Do not correct the scripts.** The unfinished sentences and repetitions are
  deliberate — that is how film dialogue behaves, and it is what the descriptor
  asks the student to follow.

### Technical spec (deliberately forgiving)

- **One continuous file per scene** — actors perform a scene, they do not record
  one clean turn at a time. The player handles a single file.
- **MP3**, mono is fine, 24 kHz or better, anything from a decent phone upward.
- Name it exactly `{level}-w{week}-scene.mp3`, e.g. `b2-w3-scene.mp3`.
- Room noise and breath are **fine** — welcome, even. Realism is the goal.

---

## How to deliver them

1. Put the files in `empire-dojo/site/audio/`.
2. Add each finished scene id to
   `empire-nexus/bots/discord-learning-bot/content/cefr/authentic_audio.json`:

   ```json
   { "scenes": ["b2-w3", "b2-w5"] }
   ```

3. Check them:

   ```bash
   cd empire-dojo && python3.12 scripts/verify_authentic_audio.py
   ```

4. Regenerate and deploy the site:

   ```bash
   EEC_REPO_DIR=../empire-nexus python3.12 scripts/generate.py
   npx wrangler pages deploy site --project-name=empire-practice --branch=main
   ```

That is all. **You can do them a few at a time** — each descriptor closes only when
*all* of its scenes are recorded (5 for `B2.R.2`, 6 for `C1.R.2`), and partial
progress is safely ignored rather than half-claimed.

---

## What happens automatically

- `scripts/verify_authentic_audio.py` **fails** if a declared scene's file is
  missing, implausibly small, or byte-identical to one of our own TTS renders
  (i.e. renamed instead of replaced). That catches the realistic mistake.
- `generate.py` switches that week's player to the single scene file. Per-turn
  highlighting goes away, which is the right trade for real tone.
- The **coverage ledger drops the reservation** for a descriptor once all of its
  scenes are declared — no code edit needed on the day.

### The one thing that is trust, not verification

Listing a scene in the manifest is **your declaration** that the audio is a genuine
human recording. No script can prove that. The checksum guard only proves the file
is not one of ours.

Please don't list a scene you haven't actually recorded — the reservation exists
precisely because it is true, and a false closure would put an unearned claim on a
student's certificate. That is the one failure mode none of this machinery can
catch.
