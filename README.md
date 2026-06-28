# Data and Evaluation Closed-Loop for Model Capability Enhancement

> A framework that turns noisy benchmark observations into actionable training-data interventions through structured capability diagnoses, with two end-to-end case studies on a continued-pretraining pipeline.

[![Paper](https://img.shields.io/badge/arXiv-preprint-b31b1b.svg)](#) [![License](https://img.shields.io/badge/license-MIT-blue.svg)](#)

---

## TL;DR

Under a fixed architecture, training objective, and optimization recipe, **training data is the principal controllable factor shaping model capability**, and **evaluation is a noisy observation of that capability**. Benchmark names are too coarse a unit to drive data decisions, and individual samples are too noisy. We introduce the **capability slice** — a group of evaluation samples sharing structured conditions along four dimensions — as the right intermediate representation, and build an analysis toolkit and closed-loop workflow around it.

The methodology produced two concrete, qualitatively different wins on the same continued-pretraining pipeline:

- **Case 1 — Output-constraint diagnosis reveals an EOS supervision bug.** A −46.82% relative BBH regression that looked like a reasoning failure was traced (via output-constraint decomposition + prediction-level audit) to a masked end-of-sequence loss. Restoring EOS supervision raised BBH from **25.14 → 66.44** (above the warm-start of 47.27), with broad gains elsewhere.
- **Case 2 — Diagnosis-aligned targeted sampling for mathematical weakness.** Near-zero Pass@128 on AIME2025/2026 was decomposed (via solving-operation analysis with pairwise and non-additive composition effects) into specific weak operation combinations. A weakness-scored Efraimidis–Spirakis weighted reservoir sampling over a synthetic instruction pool lifted AIME2025 Pass@128 from **6.67 → 26.67** and AIME2026 Pass@128 from **0.00 → 26.67**, with general-domain performance essentially unchanged.

---

## 1. Motivation

State-of-the-art pretraining is evaluated on suites that aggregate dozens of benchmarks, and headline scores are reported as single numbers attached to benchmark names. But a benchmark score is a noisy aggregate over heterogeneous sample distributions, prompt templates, decoding configurations, answer-extraction rules, and scoring protocols:

- Two models with the same MATH score may fail on disjoint kinds of problems.
- A four-point gain on a broad benchmark may reflect improved closed-book recall rather than stronger reasoning.
- A regression on BBH may originate from output-format violations rather than from any change in task-solving ability.

As long as benchmark names are treated as direct readouts of capability, the question that matters for the next training run — **what data signal, if added, reweighted, or filtered, would address the failure?** — remains under-determined.

The data side (mixture optimization, large-scale quality filtering, synthetic instruction generation) and the evaluation side (finer-grained benchmarks, sample-level failure analyses) are both mature literatures. **What is comparatively under-developed is the interface between them.** This work develops that interface.

---

## 2. Conceptual Framework

Three central objects (evaluation, model capability, training data) and two directions:

- **Causal / training direction.** `Training Data → Model Capability → Evaluation`
- **Engineering / optimization direction.** `Evaluation Failure → Capability Diagnosis → Data Intervention`

The unifying abstraction is the **capability slice** — a group of evaluation samples sharing structured conditions along four dimensions, more specific than a benchmark and more stable than a single sample:

| Dimension | Question it answers |
| --- | --- |
| **Background condition** | What information must the model condition on? (language, domain, parametric vs. contextual need, context scope, discourse form, ambiguity/noise) |
| **Task type** | What task is the model asked to perform? (factual QA, passage QA, formal math, code generation, …) |
| **Solving operation** | What operations are required to derive the answer? (fact_recall, evidence_aggregation, equation_formulation, symbolic_transformation, constraint_tracking, boundary_case_reasoning, …) |
| **Output constraint** | In what form must the answer be produced and scored? (answer form / space, scoring rule, format rigidity, exactness, explanation required) |

A failure is meaningful only when consistent across structurally similar samples — and capability slices do not align with benchmark boundaries in either direction: samples from different benchmarks may belong to the same slice, and samples from the same benchmark may belong to different slices.

---

## 3. Analysis Toolkit

Three components, jointly instantiating the conceptual framework.

### 3.1 Evaluation Sample Taxonomy

Decomposes each benchmark sample along the four dimensions above. Instantiated on **16 widely-used pretraining benchmarks**: PIQA, HellaSwag, MMLU, TriviaQA, RACE, DROP, MMLU-Pro, BBH, C-Eval, CMMLU, AGIEval-CN, MBPP, HumanEval, GSM8K, MathQA, MATH (Minerva).

Built via multi-round human–LLM co-design, with each sample independently labeled by two strong LLMs (DeepSeek-V3.2 and Qwen3.5 Plus) under the same prompt; agreements accepted after a sanity check, disagreements routed to human adjudication.

**Three uses:**
- Characterize what a benchmark actually measures (heterogeneity below the name).
- Localize weak capability slices below the benchmark level.
- Decompose post-intervention score changes by capability source.

### 3.2 Non-instruction Data Taxonomy

Characterizes raw corpus segments by the learnable signals they supply, along four perspectives that form a content-to-signal progression:

```
Content World  →  Discourse Structure  →  Operation Opportunity  →  Supervision Density
   (what)         (how organized)         (what's demonstrated)     (how learnable)
```

- **Content World** — domain (two-level), entity / concept extraction, text embedding.
- **Discourse Structure** — surface form (primary + secondary) and internal dependency (pattern, scope, density).
- **Operation Opportunity** — 9 multi-label operation types (knowledge_and_concept_grounding, evidence_localization_and_integration, comparison_contrast_and_exclusion, temporal_causal_and_process_reasoning, quantitative_and_symbolic_reasoning, constraint_and_state_tracking, simulation_and_script_reasoning, algorithm_and_code_reasoning, boundary_exception_and_failure_reasoning), each with sub-type labels.
- **Supervision Density** — a sequential gate: cleanliness (noise profile, text cleanliness, learnable signal) → knowledge density.

Annotated at scale by compact LLM annotators (Qwen3 30B-A3B / Gemma4 26B-A4B), with rule-based checks, sampled human audits, and distribution-level sanity checks. The four perspectives are deliberately designed to be **approximately aligned** with the four evaluation-side dimensions — close enough to bridge, not so close as to flatten data-side structure.

### 3.3 Evaluation-to-Data Mapping Rules

The bridge between the two taxonomies, in two layers.

**Taxonomy-aligned rules** — four dimension-level correspondences built into the taxonomies by design:

| Evaluation-side | Data-side | Notes |
| --- | --- | --- |
| `domain` | `domain` | Identical fine-grained label space. |
| `discourse form` | `discourse form` | Shared label space; corpus segments noisier and more hybrid than benchmark samples. |
| `context scope` | `dependency scope` | Aligns information-span requirements, not surface length. |
| `solving operation` | `operation opportunity` | The central mapping; typically many-to-one or many-to-many. |

Output constraint has no non-instruction-data analogue (raw text has no scoring rule); task type, language, parametric–contextual need, and ambiguity-noise are addressed by the more direct instruction-data side of the bridge.

**LLM-assisted rules** — for slices that fall outside the clean correspondences, a strong LLM proposes candidate data affordance profiles (target labels, retrieval/reweighting criteria, synthesis specs, validation slices) given the slice, both taxonomies, and representative failed examples. The LLM is a planning mechanism, not evidence: every suggestion is subject to controlled experimental validation.

**Important framing.** Mapping rules are **structured heuristics for generating data-intervention hypotheses, not causal claims.** A benchmark failure may arise from multiple compounding factors; the rules indicate what data signal to inspect, retrieve, or construct.

---

## 4. The Closed-Loop Workflow

```
   ┌────────────────────────────────────────────────────────┐
   │                                                        │
   ▼                                                        │
Weak Capability Slice                                       │
   │   [mapping rules]                                      │
   ▼                                                        │
Data Affordance Profile                                     │
   │   [data action: retrieval / reweighting /              │
   │                 synthesis / filtering]                 │
   ▼                                                        │
Controlled Experimental Validation                          │
   │   [re-evaluate along original slice]                   │
   └────────────────────────────────────────────────────────┘
```

This is the operational form taken by the data–evaluation closed loop once the mapping rules are in place.

---

## 5. Case Study 1 — Output-Constraint Diagnosis Reveals an EOS Supervision Bug

**Setup.** A MoE warm-start checkpoint (36 layers, hidden 2880, 128 routed experts, top-8 routing) is continued-pretrained for 200B tokens on a 50% general / 30% math / 20% code mixture, producing `base`.

**Observation.** Nearly every benchmark improves (TriviaQA +29.5%, MMLU-Pro +36.7%, MATH +45.8%, …). **BBH is the sole exception**, dropping 47.27 → 25.14 (−46.82% rel). The natural first hypothesis is that continued pretraining degraded multi-step reasoning.

**Diagnosis via output-constraint decomposition.**
- BBH is by construction a strict-output benchmark: 87% of items at the highest format-rigidity, 100% at the highest exactness, 94% scored by exact-match.
- Regression broad across every output-constraint value, but largest on the closed-set / MCQ subsets (50.30 → 25.86, 47.48 → 21.18) — too large to attribute to increased reasoning difficulty on items with a small finite answer set.

**Prediction-level audit (n = 5545).**
| Metric | Warm-start | Base |
| --- | --- | --- |
| Gold answer appears as prefix of `filtered_resps` | 50.39% | **69.25%** |
| Accepted by scorer when gold answer is prefix | 99.82% | **37.34%** |
| Cases with extra suffix after gold answer | 0.18% | **62.66%** |
| Mean suffix length (chars) | 0.01 ± 0.28 | **394.18 ± 733.48** |

The base checkpoint **reaches the correct answer more often**, but trails off into extra content that violates exact-match scoring. ~60% of suffixes begin with `<begin_url>` — a document-start token in our pretraining format.

**Root cause.** A pipeline audit revealed that `<EOS>` is correctly placed as a document separator in the serialized data, but **its loss is masked** during continued pretraining. The model can attend to EOS but is never directly supervised to predict it — there is no explicit termination signal.

**Intervention.** Single-variable: unmask EOS loss. Data, architecture, optimizer, all other hyperparameters unchanged. Result: `exp`.

**Result.**

| Benchmark | Warm-start | Base | Exp |
| --- | --- | --- | --- |
| BBH | 47.27 | 25.14 | **66.44** |
| HumanEval | 28.05 | 32.32 | **42.07** |
| GSM8K | 53.60 | 68.54 | **71.34** |
| DROP | 38.56 | 42.74 | **46.47** |

- Filtered-response median length: **96 → 3 chars** (matching warm-start).
- Gold-prefix acceptance: **37.34% → 99.69%** (matching warm-start 99.82%).
- The intervention **does not change how often the correct answer is reached** (prefix rate 69.25% → 69.31%) — it suppresses unwanted continuations.

**Lesson.** What looked like a reasoning regression was a termination-supervision gap. Output-constraint analysis is a primary diagnostic axis — conflating expression / scoring failures with capability failures sends data interventions at the wrong target.

---

## 6. Case Study 2 — Diagnosis-Aligned Targeted Sampling for Mathematical Weakness

**Observation.** The warm-start checkpoint scores 7.47 / 0.05 / 0.00 on MATH500 / AIME2025 / AIME2026 Pass@1. **AIME2026 stays at 0.00 even at Pass@128** — increasing the sampling budget does not surface a single valid trajectory, indicating the gap is not one test-time scaling can resolve.

### 6.1 Three-level operation-level diagnosis (n = 9,304 over GSM8K + MathQA + MATH-Minerva)

**Level 1 — Raw error rates** over inclusive single / pair / triple operation slices. The dominant operations are `arithmetic_computation`, `concept_alignment`, `multi_hop_composition`, `equation_formulation`. Highest error rates among high-support single operators: `constraint_tracking` (75.6%), `boundary_case_reasoning` (74.3%), `counting` (66.5%), `symbolic_transformation` (61.3%).

**Level 2 — Pairwise effect** Δ_pair(u; o): how anchor accuracy changes once composed with companion o.

```
arithmetic_computation (49.14% in isolation):
    + fact_recall                    →  −6.8%
    + symbolic_transformation        →  −22.8%
    + counting                       →  −31.2%
    + boundary_case_reasoning        →  −50.6%
    + constraint_tracking            →  −51.3%
```

Same pattern across `equation_formulation`, `multi_hop_composition`, `symbolic_transformation`: arithmetic-related companions are nearly neutral, while `constraint_tracking` and `boundary_case_reasoning` are systematic difficulty amplifiers.

**Level 3 — Non-additive composition effect** C(u; o_i, o_j) = r(u, o_i, o_j) − [r(u, o_i) + r(u, o_j)]. Triples whose difficulty exceeds the sum of their pairwise effects. Strongest super-additive degradation involves `counting`, `compare_or_rank`, and `symbolic_transformation`, particularly when combined with `equation_formulation`.

→ **The mathematical weakness is a composition problem, not isolated arithmetic failure.**

### 6.2 Diagnosis-aligned weighted reservoir sampling

For each operation-combination feature F (single / pair / triple), combine the three diagnostic levels:

```
Weak(F) = ω(F) · [ A_raw(F) + A_pair(F) + A_comp(F) ]
```

where ω(F) = log(1 + n(F)) · √(n(F) / (n(F) + κ)) is a support-reliability factor and the three terms are positive only when F is over-represented among errors / destabilizes its anchor / interacts super-additively.

**Feature pool construction.**
- All single operators retained.
- Top-M operation pairs by `Weak(F)`.
- Triples filtered by support (n ≥ 30) and non-additivity (A_comp > 0), top-K retained.

**Matching and sampling.** Each synthetic instruction example s is matched to features via its solving-operation labels; its sampling weight is `w_s = max_{F ∈ Hits(s)} Weak(F)`. The matched pool is sampled via **Efraimidis–Spirakis weighted reservoir sampling without replacement** with per-slot exponential-race keys `k_s = −log(u) / w_s`, under a duplication cap `d_max = 2`. A small fraction ρ of the budget is reserved for uniform sampling from the unmatched pool to preserve distributional coverage.

### 6.3 Results

**Zero-shot Pass@K on hard mathematical and code benchmarks** (warm-start / base / exp):

| Benchmark | Pass@1 | Pass@16 | Pass@32 | Pass@128 |
| --- | --- | --- | --- | --- |
| MATH500 | 7.47 / 7.33 / **7.97** | 46.12 / 45.73 / **48.97** | 57.94 / 57.87 / **61.39** | 76.00 / 77.20 / **81.00** |
| AIME2025 | 0.05 / 0.05 / **0.73** | 0.83 / 0.83 / **8.65** | 1.67 / 1.67 / **13.44** | 6.67 / 6.67 / **26.67** |
| AIME2026 | 0.00 / 0.08 / **0.47** | 0.00 / 1.20 / **6.32** | 0.00 / 2.30 / **10.84** | 0.00 / 6.67 / **26.67** |
| HumanEval | 18.22 / 16.65 / 17.82 | 58.14 / 55.54 / **58.94** | 67.62 / 65.06 / **68.54** | 84.76 / 80.49 / 83.54 |

General-domain benchmarks essentially unchanged.

**Slice-level attribution (controlled comparison, base vs. exp).** Top-10 retained operation triples:
- Few-shot protocol on diagnostic set: mean Δ_acc = +0.18pt, 8/10 improve.
- **Pass@128 protocol on MATH500: mean Δ_acc = +4.47pt, 10/10 improve.**

The Pass@K signal is roughly an order of magnitude larger than the few-shot signal and uniformly positive on the targeted slices. This is the **expected signature of an intervention that broadens trajectory coverage rather than sharpening an already-correct mode** — consistent with the widening exp–base gap as K grows on AIME (Pass@1 0.73 vs Pass@128 26.67 on AIME2025).

### 6.4 Lessons

- Mathematical weakness is better characterized as a **composition problem** than as a deficit in any single operation.
- The **Pass@1 ↔ Pass@K gap** under a targeted intervention is informative: a widening gap with increasing K is the signature of newly-acquired but not-yet-modal reasoning paths.
- **Slice-level attribution under two protocols matters** — under Pass@1-style few-shot evaluation, constraint-tracking-heavy slices appeared limit-cases; under Pass@K, the same slices improve substantially, revealing the limitation as a measurement artefact of modal-completion scoring rather than as evidence the intervention failed there.

---

## 7. Limitations

What this work does *not* establish:

- **Mapping rules are structured heuristics**, not causal claims. Every intervention they suggest remains subject to controlled experimental validation.
- **Generalization.** Taxonomies were instantiated on 16 pretraining benchmarks and a single continued-pretraining pipeline; their stability across model families, training stages, and evaluation suites remains to be tested.
- **Branch coverage.** The case studies exercise the instruction-data branch of the mapping; a parallel non-instruction-data intervention — retrieving, reweighting, or filtering pretraining corpus segments by the same affordance profile — is the symmetric test, left to future work.
- **Sampling design.** The Section 6 procedure uses one specific composite score and a duplication factor of 2; systematic studies of weight calibration, larger duplication bounds, and alternative score formulations are left to future work.
- **Synthesis-side coverage of constraint tracking.** The few-shot signal on `constraint_tracking`-bearing slices was at the noise floor (though Pass@K recovers it). An instruction-synthesis pipeline that exercises constraint tracking more directly — especially in isolation, where the single-operator pool is sparsest — is the natural next iteration.

---

## 8. Future Directions

Two directions worth pursuing in parallel:

1. **Push the loop earlier into the training pipeline.** Apply the same diagnosis-intervention-validation cycle during corpus construction rather than after a checkpoint has been trained, so that data affordance profiles inform mixture design from the outset rather than corrective sampling at the end.
2. **Refine the diagnostic side.** As benchmarks become saturated, operation-level and constraint-level decompositions may become the primary place where progress is observable; tools for tracking these decompositions across training runs may become a more useful signal than aggregate score curves.

The methodology is intended to **make existing data-curation pipelines more auditable, more directly tied to observed model behavior, and easier to iterate on** — not to replace them.

---

## Repository Layout (planned)

```
.
├── paper/                          # arXiv preprint and figures
├── taxonomies/
│   ├── evaluation_sample/          # 4-dim labels for 16 benchmarks
│   └── non_instruction_data/       # 4-dim labels for corpus segments
├── annotation/
│   ├── prompts/                    # human–LLM co-designed prompts
│   └── pipelines/                  # large-scale annotation infra
├── analysis/
│   ├── slice_diagnostics/          # weak-slice discovery
│   ├── pairwise_effects/           # Δ_pair analysis
│   └── composition_effects/        # C(·) non-additive analysis
├── sampling/
│   └── es_reservoir/               # Efraimidis–Spirakis weighted sampling
│                                   # with duplication cap + coverage reserve
└── case_studies/
    ├── case1_eos_supervision/
    └── case2_targeted_math/
```

---

## Citation

```bibtex
@article{li2026data,
  title   = {Data and Evaluation Closed-Loop for Model Capability Enhancement},
  author  = {Li, Zhixuan and Yuan, Jiangan and Xu, Han},
  journal = {arXiv preprint},
  year    = {2026}
}
```

## Authors

Zhixuan Li\*, Jiangan Yuan\*, Han Xu  *\*Co-first authors with equal contributions.*
