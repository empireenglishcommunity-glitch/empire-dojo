# Audio storage: why `site/audio/` is committed directly, and not in Git LFS

**Decision (2026-08-28): keep committing the audio directly. Do NOT move it to
Git LFS.** Use `git clone --depth 1` if clone size is ever a nuisance.

This started as an offered enhancement ("move `site/audio/` to LFS"). Investigating
it properly turned up numbers that argue the other way, so this records the
reasoning rather than quietly dropping it.

---

## The measured situation

| | |
|---|---|
| `site/audio/` in the working tree | **206 MB**, 1,095 MP3s |
| `.git` | **507 MB** |
| therefore held in history | **~301 MB** of superseded audio |
| commits touching `site/audio/` | 11 |

The ~301 MB is not waste from carelessness — it is previous *full re-renders*. The
465 extended-listening clips were re-rendered more than once, most recently when
the per-voice pace defect was fixed (delivery speed had been decided by whichever
TTS voice a script named). Each full pass writes 465 new blobs.

**That fact is the whole argument**, because it is exactly the pattern LFS handles
worst.

---

## Why LFS is the wrong tool here

GitHub gives each account **1 GiB of LFS storage and 1 GiB of bandwidth per month**
free; beyond that, a data pack is **$5/month for 50 GiB** of each
([GitHub docs — storage and bandwidth](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-storage-and-bandwidth-usage),
[GitHub docs — LFS billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-git-large-file-storage/about-billing-for-git-large-file-storage)).
Crucially, **bandwidth resets monthly but storage does not** — LFS storage is
cumulative across every version ever pushed.

Apply that to this repository:

- Migrating history would drop **~500 MB straight into LFS storage** — half the
  free quota on day one.
- Every future re-render adds **another ~206 MB permanently**. Two or three more
  passes and we are past 1 GiB and paying, *forever*, for audio we regenerate
  anyway.
- Anyone who clones without the `git-lfs` client gets **pointer files instead of
  audio** — a new way for the site to be silently broken locally.
- `git-lfs` is **not installed** in the build environment this project deploys
  from, so it would become a new hard dependency of releasing.

LFS is built for large assets that change rarely. Ours are **derived assets that
are rewritten wholesale**. That is close to the worst case for cumulative storage.

*(Content was rephrased from GitHub's documentation for licensing compliance; the
quota figures are theirs.)*

---

## Why a history rewrite is worse than the problem

`git lfs migrate import --everything` would shrink `.git`, but it rewrites every
commit, which means:

- **force-push**, invalidating every existing clone;
- **every commit SHA changes** — and the chronicle cites dojo commits by SHA (e.g.
  `empire-dojo` **6ec026cb** in `empire-chronicle/README.md`). Those references,
  and any commit links in merged PRs, would point at nothing. We would be trading
  disk space for a broken audit trail, on a project whose whole value has been
  keeping the audit trail honest.

Not worth it for a cost that is measured in seconds of clone time.

---

## What actually solves the real complaint

The genuine cost of a 507 MB `.git` is **clone time**, and that has a free fix:

```bash
git clone --depth 1 https://github.com/empireenglishcommunity-glitch/empire-dojo.git
```

That fetches one commit's worth of tree — no history, no LFS, no rewrite, nothing
to maintain. Deepen later if needed with `git fetch --unshallow`.

Deployment is unaffected either way: `wrangler pages deploy site` uploads from the
local working tree and never consults git history.

---

## The option worth revisiting later (but not now)

**Stop committing derived audio at all.** It is 100% reproducible — the scripts are
in `empire-nexus`, the renderer is `scripts/render_broadcast_local.py`, and the
model URLs are in `docs/AUDIO-RENDER-RUNBOOK.md`. Dropping it would keep the repo
permanently lean.

The cost is operational and real: a fresh machine would need to download the
~340 MB Kokoro model and spend roughly an hour rendering **before it could deploy
anything**. That makes an emergency redeploy slow, which is a bad trade for a live
programme with students on it.

Revisit if `.git` becomes genuinely painful, or if audio moves to an R2 bucket and
the site references it by URL instead of shipping it.

---

## What was done instead

- **`.gitattributes`** added, marking `*.mp3`/`*.wav`/images/`*.onnx` as binary
  with `-diff -merge`, so git stops attempting textual diffs and three-way merges
  on 1,095 MP3s during rebases and large PRs. Explicitly **no `filter=lfs`**.
- This decision recorded, with the numbers, so the question is settled rather than
  re-litigated every time the repo feels large.
