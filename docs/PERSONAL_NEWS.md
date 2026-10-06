# Personalized News Radar

News Radar uses the existing collect → cluster → verify → rank → deliver workflow,
source registry, task lifecycle and Morning Brief collector. No new daemon or UI
was introduced. Collection and selection are deterministic and do not call a model.

The catalogue now includes Hugging Face (broad AI/ML), Managing Madrid (independent
club coverage, not the official club), and Макфакс's Macedonia section. Existing
Мета/Телма/Слободен Печат registrations retain their topics and gain the user's
`macedonia news` topic so source resolution can include them. Other interests and
sources are preserved.

Only explicitly subject-specific catalogue feeds can supply `coverage_topics`.
The configured URL must match the catalogue URL. This is relevance metadata,
not evidence that a publisher's claims are true. Broad domestic publishers still
need article text to match the interest; their foreign news is not automatically
treated as domestic news. Explicit avoided interests override coverage metadata.

Selection cycles through primary matched topics while retaining ranked order
inside each topic. Both held and delivered articles consume total/source caps.
Relevance alone no longer promotes a news item to WARNING. NOTICE delivery follows
the configured notification policy: with an `important` minimum it is held for the
briefing; users who explicitly choose `briefing` can receive it immediately.

The API briefing and Morning Brief use the same bounded selector (2,000 candidate
rows), default 24-hour window and source diversity cap. Stale publication dates,
dismissed items and duplicates are excluded. Unknown dates remain explicit.
Morning Brief details include publisher ID, publication time and a short original
publisher excerpt. English articles are not silently labelled Macedonian summaries.
Local-model translation/synthesis and a completed 24-hour endurance run remain
future work; neither is claimed by this validation.

## Reproduce

```bash
cd /home/stamenovmartin/aries
./scripts/aries-news-demo
```

This runs the real news and brief automations and writes JSON evidence and a linked
Markdown report under `experiments/news/<UTC timestamp>/`. Nonzero exit means a
required coverage or pipeline check failed. It requires enabled sources/interests
covering AI, Real Madrid and Macedonian news. It does not alter interests or feeds.
Repeated scans use persisted item identities to avoid repeated delivery. It does
not claim HTTP conditional caching or a 24-hour uptime measurement.

Validation on 2026-09-18: all 8 demo checks passed, including all three subjects in
the actual persisted Morning Brief. The scan had one failed source out of 20
(Google AI connection failure); individual failures remain in `news-history.json`.
No account-wide the reviewing agent/Codex consumption or quota is inferred from this run.

Feed provenance: [Hugging Face's RSS announcement](https://github.com/huggingface/blog/issues/42),
[Managing Madrid feed](https://www.managingmadrid.com/rss/index.xml),
[Макфакс RSS directory and usage terms](https://makfax.com.mk/rss-2/).

## Local Macedonian summaries (2026-09-19)

`news.local_summaries` enables summarization in the existing Morning Brief news
collector. It calls `local_structured` only: cloud CLI escalation is unavailable
on this path. Each input is bounded to a title and 2,500 characters of feed excerpt.
The strict output schema permits one summary string (at most 400 characters),
never an action. A Cyrillic/language heuristic rejects obvious foreign output;
it does not prove fluency or factual fidelity. Accepted text is explicitly marked
as an unverified local AI summary. Original titles, links and dates remain intact.
Known Macedonian catalogue sources retain their original excerpts without inference.

The collector has a 90-second total budget and at most 45 seconds per inference.
Errors, timeouts and invalid output preserve original content. No hidden cloud
fallback is used. Exact source-content hashes key an expendable working cache in
`$DATA_DIR/news-summaries`: seven days/200 files, atomic writes, private permissions;
failed attempts have a one-hour cooldown. Pruning occurs when the cache is used.
Changing the prompt version invalidates previous cached output. Cache holds generated
summaries and usage, not complete source articles; deleting it is safe.

Actual run: `experiments/news/20260919T000327Z/` passed 8/8 news checks. Two of six
English items yielded accepted summaries, four fell back, and two domestic items
used original Macedonian excerpts. Repeated briefing verified all generated/fallback
entries were cached (`cached-brief.json`). This is not a claim of universal translation
quality; the installed qwen2.5:7b model remains weak at Macedonian.
