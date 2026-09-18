"""Pick the take of every approved sentence, and plan the cuts.

    python3 video-production/presenter/takes.py --job /data/video-jobs/<id> \
        --package <job>/source/package.json

A presenter who stumbles repeats the sentence (RECORDING_SCRIPT.md asks for exactly
that), so the recording holds each sentence one or more times, in script order,
with false starts in between. For every approved sentence this finds each span
of the transcript that says it, and keeps the LAST of the best complete takes (within
0.05 of the best match): the repeat is usually the take the presenter meant, but a
repeat that misreads a word loses to the cleaner take before it. Words heard outside
the kept takes are cut, and every other attempt is reported as a dropped retake.

The approved script is the authority for WHAT is said; the transcript only says
WHEN. Numbers compare by value, so "eight oh eight" is the script's "808". A sentence
that cannot be found is an error, never a guess; the one exception is a short,
claim-free sentence ("Welcome."), which is reported as omitted and left to review.

Cut rules
    start   first word start - 0.12 s, but never before the previous heard word ends
    end     last word end + 0.18 s, never after the next heard word starts
    A cut therefore always lands in a gap between words, never inside one.
    Consecutive sentences that were said in one go stay one continuous range.
    A slide boundary gets a longer tail: that pause is where the layout changes.

Outputs (<job>/presenter/)
    edl.json            kept ranges in source and output time, the takes, rejected spans
    transcript.json     kept words remapped to output time (Scribe shape), for captions/QA
    slides.json         per slide: output start/end and words relative to the slide,
                        the shape storyboard/build.py consumes with --words
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "storyboard"))

from beats import collapse_numbers, numbers_in, spoken_tokens, split_sentences, strip_markers  # noqa: E402

FPS = 30
STRONG = 0.85          # a complete take
WEAK = 0.60            # below this the sentence is missing
SEEN = 0.30            # a false start worth reporting as a dropped retake
MINOR_WORDS = 3        # an omitted sentence this short, with no number or citation, is a warning
LEAD, TAIL = 0.12, 0.18
SLIDE_TAIL, SLIDE_LEAD = 0.55, 0.25
JOIN_GAP = 1.0         # sentences said in one go, with a pause shorter than this, stay joined
MIN_WORD_GAP = 0.03


@dataclass
class Heard:
    tokens: List[str]            # canonical spoken tokens
    owner: List[int]             # token -> word index
    words: List[Dict[str, Any]]  # real words only, in order, with start/end


def heard_words(payload: Any, offset: float = 0.0, allowed: Optional[set] = None) -> Heard:
    raw = payload.get("words") if isinstance(payload, dict) else payload
    words, tokens, owner = [], [], []
    for w in raw or []:
        text = w.get("text", w.get("word"))
        if w.get("type", "word") != "word" or not text or w.get("start") is None:
            continue
        end = w.get("end") if w.get("end") is not None else w["start"]
        word = {"text": text.strip(), "start": round(float(w["start"]) + offset, 3),
                "end": round(float(end) + offset, 3)}
        toks = spoken_tokens(word["text"])
        if not toks:
            continue
        words.append(word)
        for t in toks:
            tokens.append(t)
            owner.append(len(words) - 1)
    # Numbers are compared by value: "eight oh eight" and "808" are the same claim.
    tokens, owner = collapse_numbers(tokens, allowed, owner)
    return Heard(tokens, owner, words)


@dataclass
class Candidate:
    first: int                   # word indexes, inclusive
    last: int
    score: float
    coverage: float

    def as_dict(self, heard: Heard) -> Dict[str, Any]:
        return {"start": heard.words[self.first]["start"], "end": heard.words[self.last]["end"],
                "score": round(self.score, 3), "coverage": round(self.coverage, 3),
                "text": " ".join(w["text"] for w in heard.words[self.first:self.last + 1])}


def candidates(script: Sequence[str], heard: Heard, lo: int, hi: int) -> List[Candidate]:
    """Every place in heard tokens [lo, hi) that says this sentence, best-first per start."""
    n = len(script)
    out: List[Candidate] = []
    heads = set(script[:3])
    i = lo
    while i < hi:
        if heard.tokens[i] not in heads:
            i += 1
            continue
        end = min(hi, i + int(n * 1.4) + 4)
        if n >= 2:
            # A restart ends the attempt: "Present PBM as a ... servi- | Present PBM as ..."
            # is two takes, and one window over both would score the false start as the full one.
            for j in range(i + 1, end - 1):
                if heard.tokens[j] == script[0] and heard.tokens[j + 1] == script[1]:
                    end = j
                    break
        window = heard.tokens[i:end]
        sm = difflib.SequenceMatcher(None, list(script), window, autojunk=False)
        pairs = [(a + k, b + k) for a, b, size in sm.get_matching_blocks() for k in range(size)]
        if not pairs:
            i += 1
            continue
        matched = len(pairs)
        a0, b0 = pairs[0]
        a1, b1 = pairs[-1]
        # The take must begin at the sentence's beginning; the match may not start mid-sentence.
        if a0 > 2:
            i += 1
            continue
        span = b1 - b0 + 1
        score = 2.0 * matched / (n + span)
        coverage = matched / n
        # A misheard first or last word ("Review" for "Reviews") is still part of the take:
        # extend over as many unmatched heard tokens as there are unmatched script tokens.
        first_tok = max(lo, i + b0 - a0)
        last_tok = min(hi - 1, i + b1 + (n - 1 - a1))
        first_w, last_w = heard.owner[first_tok], heard.owner[last_tok]
        if first_w < heard.owner[i + b0] and heard.words[heard.owner[i + b0]]["start"] - heard.words[first_w]["end"] > 0.6:
            first_w = heard.owner[i + b0]      # a pause means the word belongs to something else
        if last_w > heard.owner[i + b1] and heard.words[last_w]["start"] - heard.words[heard.owner[i + b1]]["end"] > 0.6:
            last_w = heard.owner[i + b1]
        out.append(Candidate(first_w, last_w, score, coverage))
        i += 1
    # Collapse candidates that describe the same take (several start tokens inside it).
    best: Dict[int, Candidate] = {}
    for c in out:
        key = c.last
        if key not in best or c.score > best[key].score:
            best[key] = c
    uniq = sorted(best.values(), key=lambda c: c.first)
    merged: List[Candidate] = []
    for c in uniq:
        if merged and c.first <= merged[-1].last and c.last <= merged[-1].last + 2:
            if c.score > merged[-1].score:
                merged[-1] = c
            continue
        merged.append(c)
    return merged


def token_index_of_word(heard: Heard, word_index: int) -> int:
    for k, o in enumerate(heard.owner):
        if o >= word_index:
            return k
    return len(heard.owner)


@dataclass
class Take:
    slide: int
    sentence: int
    text: str
    chosen: Optional[Candidate]
    rejected: List[Candidate] = field(default_factory=list)
    status: str = "ok"           # ok | weak | omitted (short, claim-free) | missing


def select_takes(slides: Sequence[Dict[str, Any]], heard: Heard, allowed: Optional[set] = None) -> List[Take]:
    """Walk the script in order. For sentence k, the takes to choose from are those
    that start before the first complete take of sentence k+1 that follows k's
    first complete take; the last complete one wins."""
    flat: List[Tuple[int, int, str, List[str]]] = []
    for s_i, sl in enumerate(slides):
        for j, sentence in enumerate(split_sentences(sl.get("notes") or "")):
            spoken = strip_markers(sentence)
            flat.append((s_i, j, spoken, collapse_numbers(spoken_tokens(spoken), allowed),
                         spoken != sentence))

    takes: List[Take] = []
    pointer = 0
    total = len(heard.tokens)
    for k, (s_i, j, text, script, cited) in enumerate(flat):
        found = candidates(script, heard, pointer, total)
        strong = [c for c in found if c.score >= STRONG]
        if strong:
            horizon = total
            if k + 1 < len(flat):
                after = token_index_of_word(heard, strong[0].last + 1)
                nxt = [c for c in candidates(flat[k + 1][3], heard, after, total) if c.score >= STRONG]
                if nxt:
                    horizon = token_index_of_word(heard, nxt[0].first)
            pool = [c for c in strong if token_index_of_word(heard, c.first) < horizon]
            top = max(c.score for c in pool)
            chosen = [c for c in pool if c.score >= top - 0.05][-1]
            # Every other attempt at this sentence before the next one starts is a dropped
            # retake: false starts, and complete takes that were not the one kept.
            rejected = [c for c in found if c is not chosen and c.score >= SEEN
                        and token_index_of_word(heard, c.first) < horizon
                        and not (c.first >= chosen.first and c.last <= chosen.last)]
            takes.append(Take(s_i, j, text, chosen, rejected, "ok"))
            pointer = token_index_of_word(heard, chosen.last + 1)
            continue
        # No complete take: accept the best one nearby, flagged, or report it missing.
        near = [c for c in found if c.score >= WEAK]
        if near:
            chosen = max(near[:3], key=lambda c: c.score)
            takes.append(Take(s_i, j, text, chosen, [], "weak"))
            pointer = token_index_of_word(heard, chosen.last + 1)
        else:
            minor = (len(script) <= MINOR_WORDS and not cited
                     and not any(t.startswith("#") for t in script))
            takes.append(Take(s_i, j, text, None, [], "omitted" if minor else "missing"))
    return takes


def _frames(t: float) -> int:
    return int(round(t * FPS))


def plan_ranges(takes: Sequence[Take], heard: Heard, media_end: float) -> List[Dict[str, Any]]:
    """Group kept takes into continuous source ranges and give each cut its padding."""
    kept = [t for t in takes if t.chosen]
    ranges: List[Dict[str, Any]] = []
    for idx, t in enumerate(kept):
        c = t.chosen
        prev_end = heard.words[c.first - 1]["end"] if c.first > 0 else 0.0
        next_start = heard.words[c.last + 1]["start"] if c.last + 1 < len(heard.words) else media_end
        first_start = heard.words[c.first]["start"]
        last_end = heard.words[c.last]["end"]
        joined = (ranges and ranges[-1]["last_word"] + 1 == c.first and ranges[-1]["slide"] == t.slide
                  and first_start - heard.words[c.first - 1]["end"] <= JOIN_GAP)
        slide_end = idx + 1 == len(kept) or kept[idx + 1].slide != t.slide
        tail = SLIDE_TAIL if slide_end else TAIL
        end = min(last_end + tail, max(last_end, next_start - MIN_WORD_GAP), media_end)
        if joined:
            r = ranges[-1]
            r["src_end"] = end
            r["last_word"] = c.last
            r["sentences"].append([t.slide, t.sentence])
            r["slide_end"] = slide_end
            continue
        lead = SLIDE_LEAD if (not ranges or ranges[-1]["slide"] != t.slide) else LEAD
        start = max(first_start - lead, min(first_start, prev_end + MIN_WORD_GAP), 0.0)
        ranges.append({"slide": t.slide, "src_start": start, "src_end": end, "first_word": c.first,
                       "last_word": c.last, "sentences": [[t.slide, t.sentence]], "slide_end": slide_end})
    # Snap to whole frames so video and audio segments have identical lengths.
    clock = 0
    for r in ranges:
        f0 = _frames(r["src_start"])
        f1 = max(f0 + 1, _frames(r["src_end"]))
        r["src_start"], r["src_end"] = f0 / FPS, f1 / FPS
        r["frames"] = f1 - f0
        r["out_start"] = clock / FPS
        clock += f1 - f0
        r["out_end"] = clock / FPS
    for i, r in enumerate(ranges):
        # A cut inside one slide is a jump cut the viewer sees; the layout change hides
        # the cut at a slide boundary.
        r["jump_cut_before"] = i > 0 and ranges[i - 1]["slide"] == r["slide"]
    return ranges


def remap(ranges: Sequence[Dict[str, Any]], heard: Heard) -> List[Dict[str, Any]]:
    out = []
    for r in ranges:
        shift = r["out_start"] - r["src_start"]
        for w in heard.words[r["first_word"]: r["last_word"] + 1]:
            out.append({"text": w["text"], "type": "word",
                        "start": round(max(r["out_start"], w["start"] + shift), 3),
                        "end": round(min(r["out_end"], w["end"] + shift), 3), "slide": r["slide"]})
    return out


def slide_timeline(ranges, words, slides) -> List[Dict[str, Any]]:
    out = []
    starts = {}
    for r in ranges:
        starts.setdefault(r["slide"], r["out_start"])
    order = sorted(starts)
    total = ranges[-1]["out_end"] if ranges else 0.0
    for n, s_i in enumerate(order):
        start = starts[s_i]
        end = starts[order[n + 1]] if n + 1 < len(order) else total
        out.append({"deck_position": s_i, "audio_index": slides[s_i].get("audio_index"),
                    "title": slides[s_i].get("title"), "start": round(start, 3), "end": round(end, 3),
                    "seconds": round(end - start, 3),
                    "words": [{"text": w["text"], "type": "word", "start": round(w["start"] - start, 3),
                               "end": round(w["end"] - start, 3)} for w in words if w["slide"] == s_i]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--transcript", help="raw Scribe JSON (default: <job>/presenter/scribe.json)")
    args = ap.parse_args()
    pdir = os.path.join(args.job, "presenter")
    with open(os.path.join(pdir, "ingest.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(args.transcript or os.path.join(pdir, "scribe.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    with open(args.package, encoding="utf-8") as fh:
        pkg = json.load(fh)

    from deck import to_slides, video_deck
    slides = to_slides(video_deck(pkg)[0])
    from deck import video_script
    allowed = numbers_in(video_script(video_deck(pkg)[0]))
    heard = heard_words(payload, offset=meta["scribe_trim_offset"], allowed=allowed)
    takes = select_takes(slides, heard, allowed)
    ranges = plan_ranges(takes, heard, meta["proxy_duration"])
    words = remap(ranges, heard)
    timeline = slide_timeline(ranges, words, slides)

    kept_words = {i for r in ranges for i in range(r["first_word"], r["last_word"] + 1)}
    edl = {
        "fps": FPS, "source": meta["proxy"], "source_duration": meta["proxy_duration"],
        "output_duration": ranges[-1]["out_end"] if ranges else 0.0,
        "ranges": ranges,
        "takes": [{"slide": t.slide, "sentence": t.sentence, "text": t.text, "status": t.status,
                   "chosen": t.chosen.as_dict(heard) if t.chosen else None,
                   "rejected": [c.as_dict(heard) for c in t.rejected]} for t in takes],
        "cut_words": [w for i, w in enumerate(heard.words) if i not in kept_words],
        "summary": {"sentences": len(takes), "ok": sum(t.status == "ok" for t in takes),
                    "weak": sum(t.status == "weak" for t in takes),
                    "omitted": sum(t.status == "omitted" for t in takes),
                    "missing": sum(t.status == "missing" for t in takes),
                    "retakes_dropped": sum(len(t.rejected) for t in takes),
                    "ranges": len(ranges), "jump_cuts": sum(r["jump_cut_before"] for r in ranges)},
    }
    with open(os.path.join(pdir, "edl.json"), "w", encoding="utf-8") as fh:
        json.dump(edl, fh, indent=2)
    with open(os.path.join(pdir, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump({"words": words, "source": "presenter scribe, remapped to the edit"}, fh, indent=2)
    with open(os.path.join(pdir, "slides.json"), "w", encoding="utf-8") as fh:
        json.dump({"slides": timeline}, fh, indent=2)
    print(json.dumps(edl["summary"]))
    print("output %.2fs from %.2fs of source" % (edl["output_duration"], meta["proxy_duration"]))
    for t in takes:
        if t.status != "ok" or t.rejected:
            print("  [%s] slide %d.%d %s  (rejected %d)" % (t.status, t.slide, t.sentence, t.text[:60], len(t.rejected)))
    return 1 if edl["summary"]["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
