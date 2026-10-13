# Citations used by the follow-up preregistrations (verified 2026-10-13)

Each paper below was opened on arXiv (abstract and HTML full text), the ACL Anthology or the
NeurIPS proceedings, and each claim was checked against a quoted passage. Only the wording in the
"Claim as cited" column may be used in the preregistrations and the thesis.

Status: **peer-reviewed** (main venue or main-venue track), **workshop**, or **preprint** (also
"submitted"). Effect sizes from preprints and workshops are indicative only.

| Ref | arXiv | Paper | Status | Claim as cited |
|---|---|---|---|---|
| Arora 2024 | 2410.01627 | Arora, Jain, Merugu. Intent Detection in the Age of LLMs | peer-reviewed (EMNLP 2024 Industry) | OOS detection depends on the scope and size of the label space; all models, LLMs included, have poor OOS recall; the hybrid routes a query to the LLM only when the SetFit encoder is uncertain; negative augmentation improves OOS by more than 5% |
| Zaera 2025 (UDRIL) | 2507.01541 | Efficient Out-of-Scope Detection in Dialogue Systems via Uncertainty-Driven LLM Routing | peer-reviewed (ACL 2025 Industry) | a fine-tuned LLM makes the final decision only on high-uncertainty instances |
| Zhang 2024 | 2406.12639 | Ask-before-Plan: Proactive Language Agents for Real-World Planning | peer-reviewed (Findings of EMNLP 2024) | clarification needs are predicted from the conversation and from the agent's interaction with the environment |
| Ross 2025 | 2504.18851 | When2Call: When (not) to Call Tools | peer-reviewed (NAACL 2025) | models "often hallucinate a tool call with the missing parameters" instead of asking |
| Card 2020 | 2010.06595 | With Little Power Comes Great Responsibility | peer-reviewed (EMNLP 2020) | McNemar is the standard paired test; power depends on the accuracy difference and the agreement rate Pa (discordant rate = 1 − Pa) |
| Xie 2024 | 2404.07972 | OSWorld | peer-reviewed (NeurIPS 2024; check the track label before writing "D&B") | execution-based evaluation of computer-use agents |
| Zhu 2025 | 2507.02825 | Establishing Best Practices in Building Rigorous Agentic Benchmarks | peer-reviewed (NeurIPS 2025 D&B) | outcome validity: a check must truly indicate task success; poor checks cause false positives and negatives; mis-estimation up to 100% relative |
| Rozanov 2025 | 2410.02810 | StateAct (v3 title), REALM 2025 workshop at ACL | workshop | ALFWorld gpt-3.5 average steps 31.49 → 19.11; Qwen2.5-7B ALFWorld 0.10 → 0.46, WebShop 0.19 → 0.12 |
| Tam 2024 | 2408.02442 | Let Me Speak Freely? | peer-reviewed (EMNLP 2024 Industry) | format restrictions lower reasoning; GPT-3.5 JSON mode put "answer" before "reason" in 100% of responses. Putting the reasoning field first is **our inference**, not the paper's tested recommendation |
| Sclar 2024 | 2310.11324 | Quantifying LMs' Sensitivity to Spurious Features in Prompt Design | peer-reviewed (ICLR 2024) | up to 76 accuracy points from formatting; format performance "only weakly correlates between models" |
| Luo 2025 | 2512.21120 | ClarifyMT-Bench / ClarifyAgent | preprint | Table 5: Qwen-2.5-7B 57.9 → 88.0, Llama-3.1-8B 71.2 → 88.4 (paired t-test p < 0.05); Qwen on clear users 96.6 → 85.3. Multi-turn chat, every module an LLM call |
| Liu 2026 | 2607.10059 | AgentAbstain | preprint | paired should-act / should-abstain tasks; the best of 17 models reached 59.5% paired accuracy |
| Liu 2026b | 2608.23623 | When May an Agent Stop? Evidence-Carrying Termination | preprint | completion only with a typed certificate checked by deterministic replay; 0 unsafe completions in 288 synthetic trials |
| Advani 2026 | 2606.09863 | From Confident Closing to Silent Failure | workshop (ICML 2026) | judges rely on confident closing language rather than verified state changes |
| Lù 2025 | 2504.08942 | AgentRewardBench | preprint | no LLM judge above 70% precision; rule-based checks reject successful trajectories over inconsequential differences |
| Bui 2026 | 2603.05344 | Building Effective AI Coding Agents for the Terminal | preprint (work in progress) | a design, not a measured result: MD5 fingerprints of tool name and arguments, triggered at 3 repeats in the last 20 calls |
| Dixit 2026 | 2605.29463 | Honest Lying | workshop (ICML 2026) | programmatic trajectory failure signals instead of self-diagnosis: correct object mention 0% → 86% |
| Zeng 2025 | 2501.09766 | iTool | peer-reviewed per arXiv comment (EMNLP 2025) | BFCL irrelevance: Llama-3.1-8B 41.62, Qwen2.5-7B 64.95 |
| Liu 2025 | 2510.20036 | ToolScope | peer-reviewed per arXiv comment (ACL 2026) | selects the top-k relevant tools per query |
| Tian 2026 | 2609.22218 | Toollery | preprint | bounded top-k tool selection |
| Peng 2024 | 2410.14567 | ELOQ | peer-reviewed per arXiv comment (SIGIR 2025) | a final-layer hidden-state classifier detects RAG questions the retrieved document cannot answer |
| Broecker 2026 | 2607.04034 | The "I Don't Know" Filter | preprint | a trained filter on internal-state, logprob and embedding features suppresses uncertain function calls (BFCL irrelevance) |
| Lee 2026 | 2608.13959 | Repair, Not Improvement | preprint | compared with free generation, the grammar plus stop shifts 0.6B–4B models toward naming a tool (abstention up to −29.5 points); the author reads most of the gain as repaired output, not better judgement |
| Dong 2026 | 2607.28367 | How Benchmarks Mis-Score Computer-Use Agents | preprint | 15.3% of FAIL verdicts were wrong in 150 trajectories |
| Wang 2026 | 2605.12673 | BenchJack | preprint | near-perfect scores on most benchmarks without solving tasks; 219 flaws |
| Froger 2025 | 2509.17158 | ARE (Meta Agents Research Environments) | preprint | an environment and evaluation platform (Gaia2) |
| Bellibatlu 2026 | 2609.37315 | An Executable-Contract Audit of Tool-Using Agent Environments | preprint (submitted) | 7 tool defects confirmed across 34 audited mutating tools |
| Sehwag 2026 | 2605.17324 | ASPI | preprint | clarification replies raise prompt-injection success from 1.8% to 34.0% (o3) |
