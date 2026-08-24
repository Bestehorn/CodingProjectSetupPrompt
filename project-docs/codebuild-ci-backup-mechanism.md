# Building a self-hosted CI fallback for GitHub Actions on AWS CodeBuild

An implementation guide for a coding assistant that has been asked to keep a
repository's CI pipeline running when its GitHub Actions hosted-runner minutes are
exhausted.

The mechanism described here is hosted-first with an automatic relocation onto
CodeBuild-hosted **ephemeral** GitHub Actions runners: one build per workflow job,
torn down when the job ends, with logs and status staying in the repository's
Actions tab. It is written from a working implementation, and every claim marked
MEASURED was observed on a real repository during a real outage. Claims that were
NOT measured are labelled as such — read those labels, because several of the
tempting shortcuts in this design fail in ways that produce no artifact to debug.

Nothing here is specific to one repository. Names you must choose are written as
placeholders:

| Placeholder | Is | Example shape |
|---|---|---|
| `<runner-project-name>` | the build project's physical name | a descriptive slug |
| `<mode-variable>` | the repository variable that selects the backend | an upper-snake name |
| `<fallback-token>` | the ONE variable VALUE that selects the fallback | a lowercase word |
| `<hosted-token>` | any other variable value, i.e. the hosted default | a lowercase word |
| `<hosted-label>` | the hosted RUNNER LABEL your jobs used before | the vendor's default Linux label |
| `<vendor-prefix>` | the fixed prefix the build service requires on every runner label | fixed by the vendor |
| `<owner>/<repo>`, `<region>`, `<account>` | the usual coordinates | — |

`<fallback-token>`/`<hosted-token>` are VARIABLE VALUES; `<hosted-label>` is a RUNNER
LABEL. Keeping the two ideas separate matters in §5.3, where the whole safety posture
turns on which of them the expression compares against.

---

## 1. Decide whether to build this at all

Read this section before writing any code. Three of the four options below need no
engineering, and for many repositories one of them is the right answer. A guide
that only advocates is a bad guide.

| Option | Engineering | Rough cost at low volume | Ongoing burden | Loses |
|---|---|---|---|---|
| **Pay the hosted overage** | none — add a payment method and a spend budget | list price ≈ $0.006/min for a hosted Linux 2-core minute | none | nothing except money; keeps a single-vendor dependency |
| **Make the repository public** | none (but a product decision) | zero — standard hosted runners become free | none | privacy. This is not a CI decision |
| **Go all-in self-hosted, permanently** | the runner project only (Phase 0 below) | list price ≈ $0.005/min for the smallest general-purpose on-demand tier, plus a free monthly allowance | one credential, one project, per-job sizing | the free hosted minutes you already get, and hosted's faster wall clock |
| **This mechanism (hosted-first with fallback)** | Phases 0–2 below | as above, but only while relocated | everything in §11 | nothing, at the cost of the most moving parts |

### The cost arithmetic does not favour building it

Per MINUTE the two surfaces are near parity — the smallest general-purpose
on-demand build minute lists slightly BELOW the hosted overage minute. But the
same job is slower on the fallback: MEASURED on the reference implementation, the
dominant test job ran roughly **2–3× its hosted median**, and one full relocated
pipeline spanned ≈ 15.6 minutes wall clock against ≈ 9 billed hosted minutes for
the same work. So a relocated run costs roughly **2–3× the hosted equivalent per
run**, and both numbers land in the low tens of dollars a month at the volumes a
single repository generates.

**Conclusion: compute cost is not a reason to build this.** If the only problem is
the bill, pay the overage. The reason to build it is that you do not want the
pipeline to STOP — because a stopped pipeline means either merging unverified code
or not merging at all, and both are more expensive than any of the numbers above.

Verify the list prices against the vendor pricing pages before you decide. The
smallest tier usually carries a small non-expiring free monthly allowance; larger
tiers may not appear in every pricing snapshot.

### The maintenance burden, stated honestly

The reference implementation is, at the end of Phase 2: two workflow files, two
IaC stacks, about eight source modules, and several hundred lines of guard tests
whose whole job is to stop a plausible future edit from breaking it silently. The
parts that need ONGOING attention are:

- **two access tokens with expiries** — one broad-scoped token for the vendor's
  source credential, one narrow token for the watcher — and an expired token's
  symptom is jobs that HANG, not an error;
- **one account-level source credential**, which is not a stack resource in
  effect (§3.2) and so is operator state someone must remember exists;
- **per-job instance sizing**, which must be re-measured whenever the test suite
  grows (§10 — this is where the reference implementation got it wrong twice);
- **one shared repository variable** that every concurrent worker's runs read, so
  every write is a coordination event (§11.1).

### The decision rule

Build **Phase 0 + Phase 1** if all of: your pipeline stopping is expensive; you
already have an AWS account and an IaC pipeline into it; and you can accept
2–3× per-run compute cost while relocated.

Build **Phase 2** only if outages begin when nobody is watching. Phase 1 delivers
most of the value: it turns an outage from "CI is dead" into "flip one variable".
Phase 2 buys exactly one thing — **unattended recovery** — and it costs a Lambda,
a schedule, five alarms, a dedicated token, a secret, and every defect in §9.
That trade is worth making for a repository whose merges cannot wait for a human,
and is not worth making for one whose can.

---

## 2. Architecture: three phases, each independently shippable

```
Phase 0   runner project (IaC)  +  scratch workflow requesting a fallback runner
          ─── GO / NO-GO ───  does self-hosted dispatch work while hosted is dead?

Phase 1   one repository variable, read by every job's `runs-on`
          flipped BY HAND;  hosted is the resolved default for every other value

Phase 2   scheduled watcher:  detect the refusal → flip → retry blocked work
                              → probe for recovery → flip back
```

Each phase is valuable alone and none of them requires the next:

- **Phase 0 is the go/no-go gate, and it is a measurement, not a formality.** The
  vendor documentation does not promise that self-hosted dispatch survives a
  hosted-minutes block. The billing documentation says usage "is free for
  self-hosted runners" and that the blocking language applies to metered hosted
  usage — but that is a statement about BILLING, and whether the queue-and-assign
  path for a self-hosted job still functions once an account is blocked is a
  separate question the docs do not answer. It had to be measured. MEASURED on the
  reference implementation during a real outage: attempt 1 of a run was refused on
  hosted runners; after ONE variable flip, attempt 2's jobs were assigned real
  fallback runners with non-empty runner names. **Had those jobs HUNG instead,
  self-hosted dispatch would also have been blocked and the whole design would
  have collapsed to "pay the overage".** Do not skip this. Measure it on your own
  account, during a real refusal, before building Phases 1–2.
- **Phase 1 is where the pain goes away.** One variable, six `runs-on`
  expressions, hosted as the resolved default. An unset variable is a no-op, so
  merging it cannot regress normal operation.
- **Phase 2 automates the two flips.** It is the only phase that can act on its
  own initiative, and therefore the only phase whose defects can relocate your
  pipeline for reasons you did not intend. §9 is the list.

### Deliberately NOT in this design

| Rejected | Why |
|---|---|
| Mirror the pipeline on a native build service | The run must stay a GitHub Actions run — otherwise every consumer (checks, PR UI, branch protection) loses it, and you now maintain two pipeline definitions that drift |
| A persistent self-hosted runner host | Always-on cost, patching burden, snowflake state, and cross-job credential persistence. Dominated by one-build-per-job ephemerality |
| A Kubernetes runner controller | Requires operating Kubernetes for one repository |
| A third-party spot-EC2 runner stack | Genuinely cheaper compute and a strong option at organisation scale with many repositories; needs a different IaC toolchain, an app registration, a webhook and several functions — out of proportion for one repository |

---

## 3. Phase 0 — the runner project, and the measurement that gates everything

### 3.1 The runner project

ONE build project of the vendor's "runner project" type, whose source is your
repository and whose webhook is filtered to the queued-workflow-job event. When a
workflow job requests a matching label, the service starts one ephemeral
self-hosted runner for that job and terminates it when the job ends.

Decisions worth copying, each with the failure it prevents:

| Decision | Why |
|---|---|
| **An explicit, stable PHYSICAL project name** — never an IaC-generated one | The project name appears VERBATIM inside every `runs-on` label (§4). A mismatch means the webhook is not processed and **the job hangs** rather than failing. Derive the label from the same constant the IaC uses, and pin the two equal in a test |
| **EXACTLY ONE webhook filter group containing EXACTLY the queued-workflow-job event** | A push or pull-request event here starts a NON-runner build on every commit: billable, pointless, and invisible in the Actions tab |
| **No buildspec at all** | The buildspec is IGNORED for a runner build unless the workflow asks for an override — the service replaces it with the runner setup commands. Supplying one is inert at best and misleading at worst |
| **Build-status reporting DISABLED** | A runner build's result is reported through the Actions job it hosts. Leaving reporting on posts duplicate commit statuses and needs a permission you should not hold |
| **Report-group permissions DISABLED** | Drops the report-create/update grants the IaC adds by default. A runner build publishes no test report, and an unused grant is a standing privilege for no benefit |
| **Build timeout ABOVE your longest job timeout** | The build lives exactly as long as the job. Set it below and the service kills a healthy job mid-flight. Reference implementation: longest job 90 min, build timeout 120 min |
| **A queued timeout** | Fails loudly if capacity is unavailable instead of hanging a workflow job forever |
| **A concurrent-build limit, as a deliberate COST ceiling** | Bounds how many billable runner builds can be in flight, so a webhook storm or a misconfigured matrix cannot fan out without bound. Size it at ~2× your job count so one full run plus a concurrent re-run fits |
| **Owner and repository as validated stack INPUTS, not literals** | Refuse absent or malformed values at synth. Otherwise a forgotten context value synthesizes a project whose source location is empty — failing only when the webhook cannot be created, or worse, creating a webhook on the WRONG repository |
| **The whole stack OPT-IN** | Register it only under an explicit flag, so the routine deploy path is byte-for-byte unchanged and `deploy --all` can never create it |

Also check, read-only, the account's concurrent-build quota for each compute type
you will request. MEASURED on the reference account: 300 concurrent builds for
each of the two sizes in use, against a peak of 3 concurrent builds (6 per run in
total, because the job dependency graph serialises the rest) — roughly 50×
headroom, so no quota increase was needed and the project's own concurrent-build
limit was the binding constraint. Measure yours; do not assume this one.

### 3.2 The source credential — where the reference implementation got it wrong

The build service needs a credential to talk to the git host (to create the
repository webhook and read the source).

**A correction worth recording, because the wrong version was expensive.** The
reference implementation's runbook once asserted that this credential was
account-level state that CloudFormation could not express AT ALL. That was FALSE.
The false version parked the entire build-out on a manual operator step and then
propagated into a later session that escalated to a human on the strength of it.
What is actually true:

- There **is** a CloudFormation resource type for the source credential, and an L2
  construct whose token takes a secret reference. Synthesized, the L2 renders a
  `{{resolve:secretsmanager:…}}` **dynamic reference**, so no token lands in the
  template or the cloud assembly. (The L1's token field is a plain string and
  **would** put the token in the template — do not use the L1 form.)
- What survives, and is narrower: the service holds **ONE credential per (server
  type, region)**, so it is account-scoped IN EFFECT — exactly one stack in the
  account+region may declare it, and a second declaration fights the first. That
  is a real constraint on WHERE it can live, not evidence that it cannot be
  declared.
- The token it needs carries **webhook-administration scope**, which is a broader
  shape than anything else in this design needs. Do not reuse it for the watcher
  (§11.5), and do not reuse the watcher's token for it.
- The safe (L2) form needs a secret created and populated out of band, which is
  itself operator work (§11.6).

If you find yourself writing "IaC cannot express this", check it. The generalisable
lesson: **an incorrect impossibility claim in a runbook is worse than a missing
step, because it stops anyone from looking again.**

### 3.3 The go/no-go measurement

Build a **scratch** workflow — dispatch-triggered only, deploying nothing — whose
jobs request a fallback runner, and dispatch it while hosted capacity is actually
refusing work.

**PASS** = at least one job carrying a fallback-prefixed label **and** a non-empty
runner name, with steps executed. **FAIL** = the job sits queued forever with no
runner assigned. On FAIL, stop building: the fallback surface is blocked by the
same condition and the honest answer is to pay the overage.

Two properties the scratch workflow must have:

- **It must not mutate anything.** Where your real pipeline has a deploy job, the
  scratch workflow gets a **toolchain-only** equivalent: prove that the language
  runtime, the IaC CLI, the cloud CLI and the repository's own entrypoints resolve
  and are runnable, without deploying. A pilot whose purpose is "does the runner
  work" must not also be the thing that mutates a shared environment.
- **Its evidence only transfers to the real pipeline if the two are pinned
  equal.** Assert in a test that the real pipeline's fallback arm requests the
  SAME project, image and instance size as the scratch workflow. Without that pin,
  a drift on either side silently invalidates the measurement you are relying on.

Retire the scratch workflow once Phase 1 is proven. Leaving it in place means two
copies of every job body, and the reference implementation measured them drifting.
Note that retiring it is not a bare deletion if guard tests reference it.

### 3.4 What Phase 0 does NOT prove

- **Not that your job bodies pass on the fallback image.** The curated image is
  usually a different OS release from `<hosted-label>`'s. It is tolerable because
  every job installs its own toolchain, but that is a claim to measure, not
  assume. MEASURED on the reference implementation: three fully-green relocated
  runs on the four non-deploy jobs.
- **Not that the credentialed jobs' bodies pass.** A toolchain-only pilot job
  covers the toolchain, not the body. Say which bodies you measured; do not let
  "all six jobs switch" become "all six job bodies were observed".
- **Not the memory sizing.** See §10 — this is where a green Phase 0 is most
  misleading.

---

## 4. The runner label contract

The label a job requests is the entire routing mechanism, and it has two documented
forms. **Choose the single-label override form.** The reasoning below is the single
highest-value thing in this document, because the alternative fails with no error,
no log and no build.

### 4.1 The two forms

| | **Single-label override** | **Separate-label** |
|---|---|---|
| `runs-on` shape | ONE scalar string | a LIST of labels |
| Overrides expressed as | extra components inside the one required label | additional list entries (`image:…`, `instance-size:…`, `fleet:…`, `buildspec-override:true`) |
| Per-job UNIQUE label required? | **No** | **Yes** |
| Compatible with a whole-expression `runs-on`? | Yes (§5) | No — a whole-array expression is not a documented shape |
| Failure when a unique label is omitted | n/a | cross-match; **the loser HANGS** |

### 4.2 The label's component order

Under the single-label form the complete label is one string with the components in
this order:

```
<vendor-prefix>-<runner-project-name>-<run-id>-<run-attempt>-<environment-type>-<image-id>-<instance-size>
```

**Count the components, not the hyphens.** The environment type and image id are
usually written as a distro name followed by an image version, so the tail of a real
label reads like ONE hyphenated pair rather than two components — which makes it easy
to conclude the label has fewer parts than it does, and to build it short. Check the
component list, not the shape.

- **`<vendor-prefix>`** is fixed by the service. It is also the string your
  refusal classifier keys on to tell a fallback job from a hosted one (§6), so
  define it ONCE as a constant and import it in both places.
- **`<runner-project-name>` MUST equal the runner project's physical name.**
  The vendor documents that otherwise "CodeBuild will not process the webhook and
  the GitHub Actions workflow might hang". This is why §3.1 insists on an explicit
  physical name and a shared constant.
- **`<run-id>`** scopes the runner to one workflow run.
- **`<run-attempt>` is not optional and its absence is subtle.** A re-run must
  request a NEW runner. If the label omitted the attempt, attempt 2 would request
  the label that attempt 1's now-terminated runner registered under, and nothing
  would ever claim the job. Since the whole recovery path in §9.2 depends on a
  re-run getting a fresh runner, an attempt-less label breaks Phase 2 silently.
- **The trailing three components are the overrides** — environment type, image
  identifier, instance size — folded into the one label instead of being separate
  list entries. This is what lets one runner project serve several sizes: the SIZE
  is chosen per job, in the workflow, with no redeploy.

### 4.3 Why the separate-label form's uniqueness requirement is a trap

With the separate-label form a runner registers with the SET of labels it was
created for, and matching is by label set. Consider two jobs in one run:

- job A requests `{required, image:…, instance-size:…, unique-A}` — four labels;
- job B requests `{required, image:…, instance-size:…}` — three labels.

Because the label COUNTS differ, a runner created for one job can be claimed by the
other. The loser then waits forever: the job shows as queued, **no runner is ever
assigned, no error is emitted, no log exists, and no build exists to inspect.**
That is the worst failure mode in the whole system, because it produces no artifact
to debug — it is indistinguishable from "the webhook never fired" and from "the
project name is wrong".

Under the single-label form the vendor documents that "each job's runner registers
with exactly one label … the multiple-job runner matching issue … cannot occur with
this format, even without a unique label on each job". MEASURED on the reference
implementation: three jobs of one run requested **byte-identical** labels
concurrently and each was assigned its OWN distinct runner.

**A note on how this was got wrong first.** The reference implementation's own
evaluation document carried "unique per-job labels are required" as an unqualified
risk mitigation for a long time. It is true — but only of the separate-label form.
Applying it to the single-label form leads you to invent per-job tags, which forces
`runs-on` back to a LIST, which makes the whole-expression switch in §5
impossible. The uniqueness requirement and the form are one decision, not two.

---

## 5. Phase 1 — the `runs-on` expression

### 5.1 The shape

`runs-on` accepts expressions, and its documented context availability list
includes the repository-variables context. So ONE repository variable can flip
every job in the pipeline with no workflow rewrite:

```yaml
runs-on: >-
  ${{ vars.<mode-variable> == '<fallback-token>'
  && format('<vendor-prefix>-<runner-project-name>-{0}-{1}-<environment-type>-<image-id>-<instance-size>', github.run_id, github.run_attempt)
  || '<hosted-label>' }}
```

(`<mode-variable>` is a name you choose — the reference implementation calls it
`CI_RUNNER_MODE`; from here on it is referred to generically.)

### 5.2 Keep it a SCALAR

A whole-ARRAY expression — `runs-on: ${{ fromJSON(…) }}` yielding a list — is **not
a documented shape.** Vendor sample code showing an array with per-ELEMENT
expressions does not license an expression that produces the whole array. Keep
`runs-on` a scalar string, which the single-label form makes possible, and pin it
with a test that asserts the single-label shape **and forbids the array form**.

This is a coupling worth stating plainly: choosing the single-label form (§4) is
what makes the scalar expression legal, and the scalar expression is what makes one
variable able to flip every job. Change either and the other collapses.

### 5.3 Compare against the FALLBACK literal, never the hosted one

`== '<fallback-token>'` — not `!= '<hosted-token>'`. The consequence is the whole
safety posture of Phase 1:

| Variable value | Resolves to | Because |
|---|---|---|
| unset / absent | `<hosted-label>` | the expression is false |
| `''` | `<hosted-label>` | not equal to the fallback token |
| `<hosted-token>` | `<hosted-label>` | not equal to the fallback token |
| `Codebuild` (wrong case) | `<hosted-label>` | comparison is case-sensitive |
| any typo | `<hosted-label>` | not equal to the fallback token |
| `<fallback-token>` exactly | the fallback label | the ONE opt-in value |

Under `!= '<hosted-token>'` every one of those rows except the third would
**relocate CI**, including a typo. The asymmetry is deliberate: an accidental
hosted resolution costs nothing, an accidental relocation moves the whole pipeline.

### 5.4 The default arm must be byte-equivalent to the pin it replaces

The false arm is the bare literal `'<hosted-label>'` — identical to the `runs-on`
value that was there before the switch. So merging Phase 1 with the variable unset
**cannot** regress normal operation, and that is a property to assert in a test,
not a hope. It also means Phase 1 is safe to merge long before Phase 0's
measurement is complete.

### 5.5 Switch the per-job knobs the same way, and leave the hosted arm alone

The fallback is slower and has a different memory budget, so at least two other
job-level values usually need to differ. Express each as the same ternary, with the
hosted arm **untouched**:

```yaml
# A mode-conditional job timeout: relax only the fallback arm.
timeout-minutes: ${{ vars.<mode-variable> == '<fallback-token>' && 75 || 30 }}
```

```yaml
# A mode-conditional test-worker bound (see §10). The EMPTY string on the hosted
# arm is deliberate: a runner whose pool size is read from a config value with a
# falsy-check falls through to its normal CPU-count path with no behaviour change
# and no warning.
env:
  <POOL_SIZE_SETTING>: ${{ vars.<mode-variable> == '<fallback-token>' && '2' || '' }}
```

Two things to get right here:

- **Pin the hosted arm absolutely and require only that the fallback arm exceeds
  it.** Then the fallback path can be relaxed later without weakening the hosted
  fail-fast ceiling.
- **Bound the fallback timeout by the runner project's own build timeout** (§3.1).
  If the job timeout exceeds the build timeout, the build kills the job and the
  job's own ceiling never fires.

### 5.6 The relocation is only real once you force a fresh `runs-on` evaluation

Setting the variable does nothing to work that has already been refused. To make
refused work re-evaluate `runs-on`, **push a new commit to the branch.** A re-run
also re-evaluates (MEASURED — see §9.2), but re-running is dangerous for a reason
that has nothing to do with runners, and §9.2 is that reason. Read it before you
reach for a re-run or a dispatch.

Then confirm the relocation actually happened: the new run's jobs must show
fallback-prefixed labels **with non-empty runner names**. A flip with no subsequent
fallback-labelled assignment is an unfinished flip, not a remedy.

---

## 6. Recognising a hosted refusal, structurally

This is the section to get right. Everything downstream — the manual procedure, the
watcher's flip, the decision about whether an exception to your merge policy
applies — rests on classifying a non-green job correctly, and three of the four
shapes are indistinguishable without per-STEP detail.

### 6.1 Duration is NOT a signal, and must be forbidden as one

The obvious detector is "failed within seconds with an empty log archive". It is
wrong, and it was measured wrong: an **unresolvable action reference** (a typo in a
`uses:` version) failed in ~9 seconds with an empty log archive on the reference
repository. A duration-keyed detector would have relocated the entire pipeline
because of a typo. Write this down where the detector lives, because "short and
empty" is what everyone reaches for first.

### 6.2 The four shapes

Fetch the per-job listing **with steps**. The terse listing is insufficient by
construction. Then place EVERY non-successful job in exactly one row:

| Shape | `conclusion` | `runner_name` | `labels` | `steps` | Route |
|---|---|---|---|---|---|
| **(A) Genuine code failure** — the DEFAULT for any red job with a runner and steps | `failure` | non-empty | any | `> 0` | Debug it. **Never** an exception, whichever runner it ran on |
| **(B) Refused hosted job** | `failure` | **empty** | a HOSTED label | `0` | Relocate (§5.6) |
| **(C) Fallback job that never started** | none yet (queued) or `cancelled` | **empty** | **fallback**-prefixed | `0` | Wait budget, then triage the fallback (§6.5) |
| **(D) Skipped by a job gate** — evidence of NOTHING | `skipped` | `None` | a HOSTED label | `0` | Ignore |

Shape (B) is three facts holding together, and only the third is about timing at
all. MEASURED on a real refused job:

```
<job-id>  completed  failure  <job-name>
    runner_name=''   runner_group_name=''   labels=['<hosted-label>']
    steps=0
```

1. **Both runner fields are EMPTY** — no runner was ever assigned.
2. **`labels` still names what was REQUESTED** — the job did ask for a hosted
   runner.
3. **`steps` is empty** — no workflow step executed, so there is nothing the job
   could have failed *on*.

An action-resolution failure inverts (1) and (3): a runner IS assigned, and the
setup steps appear before the failing one. That is a difference in KIND, which is
why it is safe to key on where a timing threshold is not.

### 6.3 The two traps, both measured

**Trap 1 — (D) mimics (B) byte-for-byte.** MEASURED: on one run the two deploy-stage
jobs presented `runner_name=None labels=['<hosted-label>'] steps=0` — identical
emptiness to a refusal — and were distinguished ONLY by `conclusion: skipped`.
**So classify on `conclusion` FIRST**, before looking at any other field. A
classifier that checks emptiness first will read every gated job as an outage.

**Trap 2 — (C) mimics (B), and confusing them is self-defeating.** A failing
FALLBACK job has the same no-runner/no-steps shape. If your predicate treats any
requested label as evidence about the hosted quota, then once you are relocated the
watcher reads its own fallback's failures as fresh hosted exhaustion, holds the
fallback forever, and **the recovery path becomes unreachable.** So "hosted labels
were requested" must mean HOSTED labels: return false for ANY label starting with
the fallback prefix, before checking the hosted set.

### 6.4 The predicate, and why it is a conjunction

```
is_hosted_quota_exhausted(jobs) :=
    jobs is non-empty
    AND at least one job FAILED and requested a hosted runner
    AND EVERY such failing hosted job was refused one
        (no runner assigned in EITHER runner field, and zero steps executed)
```

Every ambiguous input returns false, for a reason that is about the COST asymmetry
and not about caution as a style:

- Missing the start of an outage costs a delay, and a human still has Phase 1's
  manual flip.
- A false positive relocates all of CI onto different infrastructure and — via
  trap 2 — can make the recovery path unreachable.

Concretely:

- **An empty job list returns false.** No evidence is not evidence. A watcher that
  fired on a transient empty read would flip infrastructure on no information.
- **ONE failing hosted job that got a runner, or ran a step, returns false for the
  whole run.** That job failed on something; that is an ordinary CI failure.
- **Either runner field being non-empty counts as ASSIGNED.** Fail closed: any
  evidence a runner existed defeats the classification.
- **Address every field through a named constant**, shared with whatever tool
  fetches the listing, so a field rename is one edit that fails at import rather
  than a permanently-false predicate.

### 6.5 Shape (C) needs a declared wait budget, because no timeout bounds it

A job that never gets a runner never starts its clock, so the job-level
`timeout-minutes` does NOT bound it — that key bounds a job that is RUNNING. Do not
wait for a cancellation that may never arrive, and do not use a blocking
watch/poll helper that prints no clock: it will hold the terminal indefinitely and
cannot carry the elapsed evidence this branch needs.

Instead take TWO separate captures of the run-level detail (which carries
`created_at` / `run_started_at` / `updated_at`), state the wall-clock delta
explicitly, and finish with one terminal per-job-with-steps capture.

**Declare the budget before you wait, and justify it.** 15 minutes from
`run_started_at` with no runner assigned to any fallback-labelled job was
sufficient on the reference implementation: a healthy dispatch assigns a runner in
under a minute (observed on every green relocated run), and 15 minutes is
comfortably beyond any observed queue while still bounded.

Then triage the fallback surface, cheapest first:

1. **One job, in any run created after the mode variable's last update, carrying a
   fallback-prefixed label AND a non-empty runner name** proves the project, the
   source credential and the webhook are all live. If such a job exists the defect
   is narrower — a project-name mismatch in the requested label, a per-job instance
   size, a concurrency ceiling — so fix that and retry.
2. Otherwise, read-only cloud probes: does the account hold a source credential for
   this server type, and does the runner project/stack exist in this
   account+region? Note that an opt-in stack's ABSENCE is the default state and must
   never be inferred from "the account was deployed recently".
3. Note what those probes **cannot** tell you. A credential listing typically
   returns only an ARN, a server type, an auth type and a resource — **no expiry,
   no validity, no last-used** — and an EXPIRED credential presents as a HANG
   rather than an error. So "the credential is expired" may be recorded as
   INFERRED (a present entry plus a hang), never as confirmed.
4. Importing a credential and deploying an opt-in stack are usually
   human-owned actions an assistant may not perform. Escalating is a **terminal
   state**, not a licence to merge while you wait.

### 6.6 What is NOT a capacity refusal (the tempting misreadings)

- A red fallback run **with** a real runner name, steps, and a named failing step.
  That is shape (A).
- A job `cancelled` at its `timeout-minutes` with no summary line, or a broken-pipe
  / decode error from a heavy library's child process. Both are MEASURED
  resource-ceiling signatures (§10) whose remedy is a size or ceiling change.
- A permission error from a billing endpoint. If your token lacks the billing
  scope, its failure is evidence in NEITHER direction.
- A run whose relocatable jobs are green and whose only red jobs never relocated.
  The code is verified; the DEPLOY is not. Say so, with the run id and head SHA,
  and keep saying it until a subsequent default-branch run exercises that stage.
- "The flip did not seem to take" / "the fallback would probably have worked" /
  "the hang was infrastructure, so I ran it locally". Each is an evidence-free
  claim wearing this section's clothes.

---

## 7. The recovery probe, and its vacuity hazard

Recovery must not be keyed to a reset date. The monthly quota reset is not the only
way capacity returns, and hard-coding a date makes the mechanism wrong on every
other path. Instead ask the question directly: a **probe workflow** — one job, one
step — that does nothing except be scheduled on a hosted runner. Its conclusion IS
the answer:

- probe **succeeds** ⇒ hosted minutes are available again ⇒ flip back;
- probe **fails** ⇒ still exhausted ⇒ hold the fallback and re-probe later.

A red probe is therefore **not a defect and needs no debugging.** It is the expected
state for the entire duration of an outage. Write that in the file, because a red
workflow attracts well-meaning fixes.

### 7.1 The probe must be HARDCODED to a hosted runner, forever

This is the single highest-risk line in the whole feature. Every other job in the
repository now selects its runner through the mode expression, so making this one
"consistent" with them is the most natural edit anyone could make — and it would be
catastrophic **and self-concealing**:

1. During an outage the probe resolves the fallback arm.
2. It runs on a fallback runner and **succeeds**.
3. The watcher reads that success as "hosted capacity is back" and flips to hosted.
4. Every real job is refused by the still-exhausted quota.
5. The next probe again succeeds on the fallback, and again confirms the mistake.

CI ends up pinned to a dead quota **indefinitely, with a green probe explaining
why.** Nothing in the system is red. So `runs-on` here is a bare literal, and it is
guarded by tests rather than by a comment.

### 7.2 Assert EQUALITY, not containment

The mutant to fear is a verbatim copy of the switching expression — and that
expression **CONTAINS the hosted label on its false arm**. So:

```
assert rendered_runs_on == <hosted-label>        # correct
assert <hosted-label> in rendered_runs_on        # PASSES on the exact defect
```

A containment oracle passes on the precise mutation it exists to prevent. Assert
equality, against the same constant the production code uses for the hosted label,
and prove the negative: a fixture copy of the switching expression must RED the
test.

### 7.3 The guard sweep must PARSE the workflows and key on the LABEL PREFIX

State the property repository-wide as well, so a FUTURE workflow cannot acquire a
fallback runner unnoticed. The obvious sweep — grep every workflow for the raw text
of the variable reference — is wrong twice, and both ways were measured before the
guard was written:

1. **It reds against the artifact it specifies.** The probe's own header comment has
   to EXPLAIN why it must never carry the switch, and it cannot do that without
   NAMING the variable. A raw-text sweep matches that comment, so the oracle would
   demand deletion of the very explanation that stops a future agent from making
   the change.
2. **It cannot see a workflow that pins via a label LIST at all.** The scratch
   pilot workflow pins six jobs to fallback runners through a list of labels,
   containing ZERO occurrences of the variable text. A text-keyed sweep reports it
   as hosted-only — the exact OPPOSITE of the truth — so the census is
   simultaneously over- and under-sensitive.

So the sweep must:

- **parse** each workflow file and render every job's `runs-on`, handling BOTH the
  scalar and the list shape into one representation (a census that handled only the
  scalar form would silently skip every list-pinned job);
- key the negative on the **fallback label prefix** — the same constant the
  production refusal classifier uses (§6.2), so there is ONE spelling of "this job
  asked for the fallback";
- assert **SET EQUALITY** over the files permitted to request a fallback runner, so
  the guard fails on an ADDITION (a new workflow quietly pinned) as well as on a
  REMOVAL (the switch deleted, or the pilot retired without updating the census);
- glob **both** file extensions the host accepts, or the census is defeated by
  renaming a file;
- carry a **liveness floor**: a minimum file count, and an assertion that each file
  rendered at least one label. Without it, a glob that matched nothing satisfies the
  set-equality negative **vacuously** — the guard passes by censusing nothing.

That last point generalises: every negative assertion in this feature needs a
non-vacuity companion, because "nothing requested the fallback" and "we looked at
nothing" produce the same green.

### 7.4 The rest of the probe's shape, and the reason for each choice

| Choice | Reason |
|---|---|
| **Dispatch trigger ONLY** — no schedule | A schedule would spend hosted minutes unattended and forever, on the exact quota the mechanism exists to conserve — and it would mint probe runs the watcher's cadence gate never authorised, desynchronising the backoff from the probes it spaces |
| **No concurrency group** | Concurrency groups are REPOSITORY-scoped, not workflow-scoped. Reusing the pipeline's group would queue probes with real runs on the same ref: a probe could cancel a pending run, or be cancelled by one — and a cancelled probe is "not success", which reads as continued exhaustion |
| **Empty permissions** | It checks out nothing and reads nothing. It is dispatchable by anything holding the watcher's token, so any scope it held would be reachable from that credential |
| **ONE job, ONE step, NO third-party action** | Jobs are billed separately and rounded up to the whole minute, and the probe's entire output is one bit. A matrix is one `jobs` entry and N billed jobs. An action is third-party code inside the probe whose own failure would be misread as a capacity verdict |
| **`timeout-minutes` bounded on BOTH sides** (e.g. 2–5) | Too large and a hang holds a hosted runner through the outage it is measuring. Too small and a probe that is merely QUEUED — normal when capacity is tight — is cancelled by the clock and misread as "still exhausted", keeping CI on the fallback indefinitely |
| **Addressed by FILENAME on a fixed ref** | The watcher lists its runs and dispatches it by filename, so the filename is an API identifier: renaming the file changes two API paths. Hold it in one constant, and compose the run-payload `path` value from it rather than restating the path as a literal |
| **Dispatched against the default branch** | The probe file is only guaranteed to exist there; a probe aimed at a feature ref is answered with a 404 until that branch merges |

### 7.5 A runtime self-check is worth adding, and its strength is UNMEASURED

Have the step also assert at runtime that it is on a hosted runner, by comparing
the runner's self-reported environment against the expected hosted value.

Be honest about what that buys. The host documents the runner-environment context
value as having two values, one for hosted and one for self-hosted, and says
**NOTHING** about what a CodeBuild-hosted Actions runner reports. Nothing in the
reference implementation measured it either. So the check is cheap defence of
**UNKNOWN strength** — it is NOT evidence that "two independent removals are needed
for a false flip". The evidenced guard is the `runs-on` equality pin in §7.2. To
close the gap, dispatch your scratch pilot with a temporary step echoing that
context value and record what you observe.

Two implementation details that decide whether the check measures anything:

- **Thread the value through a step-level `env:` map.** An expression spliced
  directly into the shell body is substituted by the runner BEFORE the shell runs,
  so the comparison would be between two strings the workflow author chose — a
  tautology, not a measurement.
- **Nothing may follow the comparison.** A trailing command's zero exit status
  becomes the step's exit status and silently discards the verdict. (An `echo`
  BEFORE it is fine and worth having, so the value is recorded rather than assumed.)

---

## 8. Phase 2 — watcher design

A scheduled function that on each tick reads the current mode plus recent run
history and produces ONE decision. All the risk of Phase 2 concentrates here.

### 8.1 The decision is a PURE function; all I/O is outside it

```
decide(current_mode, recent_runs, probe_runs) -> Decision {
    target_mode, changed, runs_to_retry, should_probe, reason
}
```

No cloud client, no host client, no clock inside it. The surrounding function
performs only the effects the decision names. This is not architectural taste: it
is what makes the decision table testable at any instant, over any evidence, with
no infrastructure — and the decision table is the part you cannot afford to be
wrong.

Make the decision a **frozen** value object. A decision is a conclusion the
executor performs, not a scratchpad it amends. Carry a one-sentence
human-readable `reason` on every branch: that string is what an operator reads
when an alarm fires, and a decision that cannot explain itself is a decision
nobody can audit.

### 8.2 Stateless by design

The obvious question — "where does the watcher keep its state?" — has the answer
"nowhere", because its state is already observable and authoritative:

- **the current mode IS the mode variable.** The watcher writes it, so reading it
  back *is* the record of the last decision;
- **probe bookkeeping IS the probe workflow's run history**, which the host already
  keeps;
- **retry bookkeeping IS the host's own run-attempt counter** (§9.2).

A private store — a table, a parameter — would have to be kept consistent with the
variable it shadows, and any divergence would be SILENT: the mode would say one
thing and the watcher's memory another. Deriving everything from the observable
surface removes that failure mode along with the resource.

### 8.3 Read the mode EXACTLY as the workflow does

Mirror `runs-on`'s comparison: exact, case-sensitive, one token, everything else
resolves hosted. A watcher that read the variable more LIBERALLY than the workflow
does would compute decisions against a mode CI is not actually in — believing the
pipeline is relocated while every job still requests a hosted runner. Import the
resolver from one module rather than writing the comparison twice.

### 8.4 The asymmetry that shapes every rule

Neither direction is the "safe" default, and that is why both demand positive
evidence:

| Direction | Failure on weak evidence |
|---|---|
| hosted → fallback | Relocates the whole pipeline for what may be an ordinary failure (the ~9-second action-resolution shape, §6.1) |
| fallback → hosted | Returns CI to a still-exhausted quota where nothing runs — and if the watcher then reads its own fallback failures as fresh hosted exhaustion (§6.3 trap 2), **the recovery path becomes unreachable** |

So: **every ambiguous input holds the current mode.** No branch flips on the
absence of information.

### 8.5 In fallback mode, do not even ASK about refusals

While relocated, the only open question is whether hosted capacity has returned —
answered by the probe alone. Deliberately do NOT also ask "do recent runs look
refused", because a failing fallback job has the same no-runner/no-steps shape.
The classifier already rejects those by label prefix; **declining to ask at all is
a second, independent guard** on the same failure. Two independent guards on the
loop that makes recovery unreachable is the right number.

### 8.6 The probe cadence gate may only SUPPRESS

The decision function returns `should_probe=True` on EVERY fallback tick whose
newest probe failed. That is the right answer to "does this state want a probe?"
and the wrong answer to "should THIS tick dispatch one?" — a multi-hour outage
would queue one hosted job per tick, spending the exact resource being waited on.

So gate it:

```
dispatch := decision.should_probe AND window_has_elapsed
```

**The order of that conjunction is a safety property, not style.** The gate is a
second opinion on a decision already made; if it could promote a `False` to a
dispatch it would probe while CI is on HOSTED runners (burning the minutes the
mechanism conserves), probe while another probe is IN FLIGHT, and probe after a
SUCCESS when the answer is already known. It may narrow `True` to `False` and must
never widen `False` to `True`. Name that as a test.

Cadence: a base interval, doubling per consecutive failed probe, capped at a
ceiling. Details that matter:

- **Use the LEADING streak of newest consecutive failures**, not a total count and
  not "any failure". A total count keeps backing off after capacity has come back
  and gone again; "any failure" never comes down at all. An UNFINISHED newest run
  ends the streak too — it has not failed and has not answered.
- **The ceiling is the worst-case lag** between capacity returning and the watcher
  noticing, so it must not be large. An unbounded doubling leaves CI on the
  fallback for many hours after the outage ended, defeating the point.
- **Beware the off-by-one spelling.** `base * 2 ** (streak - 1)` evaluates to
  `base / 2` as a FLOAT at `streak == 0`, which is most ticks, and that value then
  flows into your telemetry. Return the base explicitly for streak 0 and 1.
- **Compare INCLUSIVELY** (`elapsed >= interval`). An exclusive comparison pushes
  every probe out by one whole tick, so the real spacing is silently the tick
  period rather than the cadence, and no "eventually a probe happens" assertion can
  see the difference.
- **State plainly what the backoff does NOT buy.** It never suppresses the first
  probes at any tick period, because rungs 0 and 1 are both the base interval and
  any sane tick is at least that. Suppression begins at the first DOUBLED rung.
- **Derive the schedule period from the base interval by IMPORT, not by writing
  the same number twice.** A cadence gate can only be evaluated when a tick runs,
  so a rung of `I` seconds is REALISED as `ceil(I / T) * T`. At `T == base` every
  rung of the ladder is an exact multiple of the tick and realised == declared. At
  any other period most rungs are mis-realised and your documented cadence
  describes something that does not happen — and no "eventually" assertion can
  detect it. A literal in the schedule satisfies every value assertion while
  breaking the derivation, so pin the derivation itself (by AST if your language
  allows), not the value.

### 8.7 Cold start is a NORMAL state, not an error

Before the first flip there is no mode variable, so a read returns "absent". Every
path must treat absent as a legitimate value — the mode resolves hosted, the
evidence floor falls back to a lookback (§9.1), and the telemetry records nulls.
The reference implementation's near-miss here: a confirm-read comparison written as
`confirmed_value == target_mode` makes the MOST COMMON production tick fail,
because a hold-steady tick on an absent variable reads as unconfirmed, the handler
raises, and the observation period becomes a wall of failed ticks behind a
permanently-firing alarm. Compare through the SAME resolution the workflow uses,
and treat a tick that attempted NO write as confirmed by construction.

### 8.8 Put the report-only seam in an OBJECT, not an `if`

Ship the watcher in report-only posture first (§11.2). That observation period is
worth nothing unless it is **structurally impossible** for a report-only tick to
act, so the posture is not a branch in the handler — it is an object, chosen once
per tick, that owns every effect:

```
WatcherEffects (abstract):  apply_mode(...) -> ModeWriteOutcome
                            retry(run_id)
                            dispatch_probe()

ReportOnlyEffects:  computes everything, performs nothing, HOLDS NO CLIENT
LiveEffects:        performs each effect through the injected client
```

The handler's execute step then holds a `WatcherEffects` and no client is in its
reach at all, so a bug in the posture CHOICE is the only way a report-only tick can
act — and that choice is a three-line function with its own test.

Details the reference implementation learned:

- **Assert the report-only object holds NO state** (`vars(instance) == {}`). One
  that held a client "for symmetry" is one attribute access away from acting.
- **Assert the two postures' public callable surfaces are EQUAL**, not merely that
  the abstract methods are implemented. Adding a concrete method to the live class
  does not change the abstract set, so an effect live has and report-only lacks
  would pass an abstract-set oracle while breaking the simulation.
- **Split "did the operator ask for acting?" from "which object performs this
  tick?"** as two functions. Folded into one, the token comparison becomes
  unreachable by any test that stubs the selector, and a test of the comparison has
  to construct a client it does not want.
- **The acting token is an exact, case-sensitive, whitespace-significant match.**
  No trim, no lowercase: a padded value is what a copy-paste into a deploy context
  actually produces, and admitting it means the operator enabled acting by
  accident. Every ambiguous value resolves REPORT-ONLY.
- **Report-only must SIMULATE the post-write anchor** (use `now` on the would-write
  path) rather than confirm-reading. A confirm-read on a tick that deliberately did
  not write returns the OLD timestamp, so the observation period would
  systematically under-report the retries the live posture would have performed —
  zeroing the one number the period exists to produce.
- **A live write must be CONFIRM-READ.** Not belt-and-braces: retries issued
  against an unwritten variable are re-refused on the same exhausted quota, burning
  the retry budget while every record reports success. And `changed == False` must
  make NO request at all — that is the overwhelming majority of ticks, against a
  rate limit the host may document per USER rather than per token.

---

## 9. The three defects that WILL bite

Each of these was reached in the reference implementation with a decision function
that was **correct on every input it was handed**. They are all about which inputs
it is handed, or what it is authorised to do with them — which is why none of them
shows up as a failing unit test of the decision table.

### 9.1 Evidence must be time-fenced, on BOTH lists

Without a time floor the watcher is **non-convergent in production** while every
individual decision remains defensible on the evidence it saw.

**Door 1 — a stale successful probe.** A probe that succeeded during the PREVIOUS
outage's recovery is still the NEWEST probe when the next outage begins. So:

```
tick N     fresh refusals            -> flip to fallback
tick N+1   reads the stale success   -> "capacity is back" -> flip to hosted (dead)
tick N+2   nothing runs there, fresh refusals -> flip to fallback
...        period ≈ three ticks, forever
```

**Door 2 — the watcher's OWN failed probes.** The probe is pinned to a hosted label
(§7.1), so a probe refused for lack of hosted minutes carries the **identical**
measured refusal signature the detector keys on: hosted label requested,
`runner_name` empty, `steps` empty. A probe run left in the general evidence list
therefore re-triggers the flip-FORWARD on the tick after any flip-back — the same
loop entered from the other side.

**And the time floor CANNOT close door 2**, which is the part that surprises: the
watcher dispatched that probe itself, so it is always NEWER than the mode currently
in effect. Closing one door leaves the other open. So one function closes both at
once:

```
floor := max( mode_variable.updated_at ,  now - LOOKBACK )

fence(runs, probe_runs) :=
    ( [r for r in runs       if r is NOT a probe-path run and r.created_at >= floor][:CAP],
      [p for p in probe_runs if p.created_at >= floor] )
```

Both floor terms are load-bearing:

- Drop the **lookback** term and an ABSENT variable admits the entire history of the
  repository as current evidence — which is exactly the cold-start tick.
- Drop the **`updated_at`** term and door 1 reopens whenever the mode changed less
  than the lookback ago, which is every tick that matters.

Sizing the lookback: it must comfortably exceed one full pipeline (so a run refused
at the start of an outage is still visible to the next tick, with room for the lag
between a run being refused and its job listing settling), and must NOT be long
enough for a months-old absent variable to admit an unrelated historical outage as
current evidence. The reference implementation uses 2 hours against a ~35-minute
pipeline. Pin it with rows at `lookback ± 60 s` so the constant cannot be silently
retuned in either direction.

**Identify probe runs POSITIVELY.** A run carrying no path field is NOT excluded.
That is a deliberate asymmetry with the probe-listing selector, which refuses a
run whose path is absent: there, an absent path fails to prove a run IS a probe;
here, it fails to prove a run is NOT ordinary CI. Inverting it — excluding anything
not provably the pipeline workflow — would discard real refusal evidence on any
payload change and make the flip unreachable.

**Cap the fenced list.** Each survivor costs one per-run job listing against a rate
limit shared with everything else using that token. The evidence is not
statistical: ONE refused run is a conclusion, and a wider window only adds
duplicates of it. Ten is ample.

**Record both counts.** `runs_considered` and `runs_after_fence` are what
distinguish "held steady because nothing was wrong" from "held steady because the
fence discarded everything" — two very different ticks that emit an otherwise
identical hold-steady record. Record the floor too, or a hold-steady tick is
unauditable.

#### The two windows point in OPPOSITE directions

This is the single most important thing to understand before wiring either:

| Question | Window | Fed with |
|---|---|---|
| "should we flip?" | evidence **NEWER** than the mode in effect | the fenced lists |
| "what work did the flip leave behind?" | runs **OLDER** than the flip: `[flip - lookback, flip]` | the runs as **FETCHED** |

The two sets are close to disjoint by construction. So the retry-target function
takes the runs as FETCHED, **not** the fenced list — feeding it the fenced list
hands it precisely the runs its own window excludes.

And its anchor is the timestamp of the mode in effect **AFTER** this tick's write —
the confirm-read value (§8.8). Passing the PRE-write value on a flip tick places the
whole window before the outage and retries **nothing**, which is the one wiring
mistake here that fails completely silently. Because the two anchors come from
opposite sides of the write, the confirm-read cannot be hoisted before the decision
and cannot be deferred past retry targeting: **the call order is forced, not
chosen.**

### 9.2 Retry authorisation must bound the TRIGGER, not just the branch

Relocating CI is only half of recovery; the work that was refused must be re-run.
A re-run DOES re-evaluate `runs-on` against the current variable — MEASURED, and
the documentation could not settle it either way, so it had to be measured. But a
re-run is also an **infrastructure-mutation capability**, and this is the defect
most likely to cause real damage.

Read a typical deploy-job gate:

```
if: github.event_name == 'workflow_dispatch'
    || (github.event_name == 'push' && github.ref == 'refs/heads/<default>')
```

**The first disjunct names NO ref.** A dispatch-triggered run therefore deploys from
whatever branch it was dispatched on. A re-run preserves the original event and ref
and re-runs the WHOLE run. Therefore:

> Re-running a refused **dispatch-triggered FEATURE-branch** run deploys that branch
> into the shared environment — passing a branch-only filter **cleanly**, because
> its head branch is not the default one.

So bound by **trigger type AND branch**, as two SEPARATE named constants:

| Constant | Covers | Rationale |
|---|---|---|
| `PROTECTED_BRANCHES` | the gate's `push && default-branch` disjunct | a re-run of a default-branch refusal re-enters the deploy job |
| `DEPLOY_CAPABLE_EVENTS` | the gate's ref-unconditional `dispatch` disjunct | the half that is easy to miss |

**Keep them separate.** They answer different questions — WHICH REF may deploy vs
WHICH TRIGGER ignores the ref — and collapsing them into one filter is precisely
what allowed the first disjunct to be **documented but unenforced** in the reference
implementation: the branch constant's own comment described the dispatch hazard
while the code checked only the branch.

Further conditions on the retry set, and each earns its place:

- **`run_attempt == 1`.** The host's own bookkeeping that nobody has re-run it yet.
  This is what makes the retry set convergent and idempotent with **no private
  state**: a retry that LANDS increments the attempt so the id drops out of the set;
  a retry that FAILED leaves it at 1 so the next tick retries it.
- **FAIL CLOSED on a missing field.** A run whose payload carries no trigger, or no
  integer attempt, is EXCLUDED. An absent field means the evidence that the gate is
  closed is MISSING, not that it is established.
- **Re-check the refusal signature here**, rather than trusting it from the
  decision. This set also bounds what the decision is allowed to act on.
- **Raise, do not skip, on an unusable id** for a run that has already passed every
  eligibility gate. Silently skipping loses refused work with nothing reporting it.

Two operational corollaries:

- **"Re-run failed jobs" is no escape** when the deploy job is itself among the
  failed jobs — which it is, during a hosted refusal.
- **Never point a dispatch at the pipeline workflow** if its dispatch trigger
  re-enters the deploy job: the dispatch is ACCEPTED and the deploy runs. If you
  want a dispatch probe, dispatch the recovery probe or the scratch pilot — both
  deploy nothing. To force a fresh `runs-on` evaluation for the pipeline itself,
  **push to the branch** (a pull-request run leaves the deploy stage `skipped`,
  which is what makes a push the safe route).

A note on the ordering claim: a stale-base or provenance guard on your deploy path
does **not** cover this. For the newest default-branch run the head SHA *is* the
trunk tip, so an ancestry check passes and the deploy proceeds.

### 9.3 One secret, two readers

The credential in this design is read from two places: the **infrastructure** (the
source credential's token reference) and the **runtime** (the watcher fetching its
token). If the infrastructure resolves a **JSON FIELD** of the secret while the
runtime reads the **WHOLE secret string**, the runtime sends the JSON document as a
bearer token and gets **401 on every call** — while the infrastructure side looks
perfectly healthy and the secret plainly contains the right token.

**The fix is structural: put the field name (or the explicit decision that there is
no field) in ONE module both sides import.** Two spellings of the same convention
are free to disagree, and the disagreement is invisible in both halves.

Concretely, decide once and encode it:

| Secret contents | Infrastructure reference | Runtime read |
|---|---|---|
| a bare token | the whole-string form | the whole secret string |
| `{"<field>": "<token>"}` | resolve `<field>` | parse and read `<field>` |

Never mix a row.

#### The status-code rule, which saves an afternoon each time

| Status | Meaning | What to change |
|---|---|---|
| **401** | wrong credential **SHAPE** — it was sent and rejected *as a credential* | how the credential is read/assembled (this defect; an empty/blank value; a JSON blob; a stale token) |
| **403** | the credential was ACCEPTED and a **PERMISSION** is missing | the token's scopes |

And: **the failing CALL in the traceback names which scope is short.** A 403 on a
variables write and a 403 on a run re-run are two different missing scopes, and
treating "403" as one condition sends you to re-mint a token that was fine.

Three corollaries worth carrying:

- **A capability probe cannot prove a WRITE scope**, because probing a write means
  mutating the repository. Expect "not probed" for every write scope, and do not
  read that as evidence in either direction.
- **An expired credential presents as a HANG, not an error**, on the runner-dispatch
  path (§6.5). Diarise the expiry; you will not be told.
- **Never let the credential reach a log.** An SDK's DEBUG rendering of a
  secret-fetch response carries the secret value verbatim, and a failure record that
  carries the response BODY of a request made with the token is a leak channel.
  Record the exception CLASS and the status code and **nothing else** — give the
  failure record no free-text channel at all, as a property. The diagnosis is not
  lost: the exception still propagates and the runtime logs its own traceback.

---

## 10. Sizing, and the ratio that makes bigger instances useless

### 10.1 The on-demand Linux tiers

| Tier | vCPU | Memory | Disk | Environment type |
|---|---|---|---|---|
| Small | 2 | 4 GiB | 64 GB | EC2 **or** container |
| Medium | 4 | 8 GiB | 128 GB | EC2 **or** container |
| Large | 8 | 16 GiB | 128 GB | EC2 **or** container |
| XLarge | 36 | 72 GiB | 256 GB | **container only** |
| 2XLarge | 72 | 144 GiB | 824 GB SSD | **container only** |

XLarge and 2XLarge are **not available in the EC2 environment type.** If your jobs
need privileged mode (Docker-in-Docker), you are on EC2 compute and the two largest
tiers are simply not reachable — check this before planning to scale up. (A
serverless-function compute type also exists with per-second billing, but it
supports neither Docker nor privileged mode.)

### 10.2 The load-bearing insight: 2 GiB per vCPU, at every size

**Every general-purpose tier is exactly 2 GiB of memory per vCPU.** 2/4, 4/8, 8/16,
36/72, 72/144 — the ratio never changes.

Now consider a test runner that sizes its worker pool from CPU count, which is what
`-n auto` and its equivalents do. It takes **one worker per vCPU**. Therefore:

> **The per-worker memory budget is IDENTICAL at every size.** Scaling up buys you
> MORE WORKERS at the same budget each — not more memory per worker.

If your failure is "one worker needs more than 2 GiB", **upsizing does nothing**. It
costs more per build-minute and fails in exactly the same place, with more workers
racing to get there. This is the trap that makes sizing feel unfixable: the obvious
remedy is arithmetically guaranteed not to work, and it is not obvious why.

**Bigger only helps if the worker count is EXPLICITLY bounded.** The two escapes:

1. **Bound the pool.** Cheapest, and the one to reach for first. Set the runner's
   worker count from configuration rather than from CPU count, and express it as the
   mode ternary (§5.5) so the hosted arm is untouched. Two workers on a 4-vCPU
   Medium gives each ~4 GiB instead of ~2 GiB — a real doubling, from a one-line
   change, with no size increase at all. Combining a bound with a size increase is
   how you buy per-worker memory: 2 workers on Large is ~8 GiB each.
2. **A reserved-capacity fleet on a memory-optimised instance family**, which
   **breaks the 2 GiB/vCPU ratio** — that is the only mechanism here that does.
   Reserved fleets also allow a **custom instance type**. But be clear about what
   changes: reserved machines are always running and bill for as long as they are
   provisioned (no scale-to-zero), and data cached on the fleet persists across
   builds, which is a materially different security posture from one-build-per-job
   ephemerality. If you have relocated credentialed jobs (§11.4), that persistence
   is the thing you were relying on NOT existing.

### 10.3 Size PER JOB, not per project

The label carries the size override (§4.2), so one runner project serves every size
and each job picks its own in the workflow with no redeploy. Size only the job that
needs it: builds are billed per build-minute BY SIZE, so upsizing jobs that already
fit costs money to prove nothing. The reference implementation runs every job on
Small except the test job, which runs Medium — chosen for **memory**, not wall
clock, and pinned by a test asserting exactly that ("only the test job requests
Medium; every other job stays Small").

### 10.4 What the wrong sizing actually looks like — and it is never a clean OOM

MEASURED signatures on the reference implementation, none of which contains the word
"memory":

| Observed | Reads as |
|---|---|
| `BrokenPipeError` raised from `import <heavy-library>` at the child process's stdin | a broken toolchain |
| A JSON decode error from the same interop layer (the child exited 0 having written nothing to either stream) | a broken toolchain |
| A job `cancelled` at its `timeout-minutes` with **no summary line and no retrievable log** | an infrastructure fault, not a slow suite |
| A 13-minute stall at a single progress percentage, then a timeout cancellation with **zero test failures** | a hung test |
| An explicit memory error, or a killed worker | memory (the only obvious one) |

The reference implementation's original signature list contained only the LAST row
plus a decode error — and **neither of the two symptoms actually observed was on
it**, so a reader matching against that list would have misclassified both.

**The durable lesson: a WALL-CLOCK sizing comparison cannot detect a memory ceiling,
and did not.** The reference implementation's sizing experiment concluded "keep the
smaller size" from wall clock alone (550 s Small vs 566 s Medium) — a perfectly
sound reading of a measurement that could not see the thing that mattered. The next
run on Small hit the ceiling. Design the sizing experiment to measure MEMORY, or it
will confidently give you the wrong answer.

Note also the diagnostic hazard in the underlying cause: when a heavy library
spawns a child process that reserves a multi-GiB heap, **the same commit produces
different symptoms on different runs** — a resource ceiling crossed at a different
point each time. Two different symptoms from one commit is a resource signal; a code
defect reproduces on the same test.

### 10.5 The reclaim livelock — the failure mode with no error at all

The nastiest shape is not an OOM kill. OBSERVED signature:

- memory sits **pinned just under the limit** rather than crossing it;
- **enormous, sustained page-cache READ throughput with flat writes** — the same
  bytes being re-read continuously;
- **near-zero CPU**, because nothing is making progress;
- **minutes of total log silence** — the job's output simply stops mid-stream;
- the host eventually marks the job **abandoned**, because the runner agent stopped
  renewing its lease;
- and **the BUILD reports SUCCESS**, because the build process itself never died —
  only the job did.

INFERRED mechanism: the kernel reclaims and re-reads instead of failing, so the
process never gets a memory error and never gets any work done either. That
mechanism is the explanation, not the observation; the signature above is what was
observed.

**How to see it: the BUILD-level utilization metrics** — memory, and disk read/write
throughput over the build's lifetime. Not the job log. The job log is the one place
this failure is invisible **by construction**, because the symptom IS the absence of
log output. If you take one operational habit from this section, take this: when a
relocated job goes quiet, open the build's utilization graphs before you read
anything else.

This is also why a "success" from the build service is not a green job, and why the
job's own conclusion is the authority.

---

## 11. Operational safety

### 11.1 The mode variable is SHARED state

It is ONE repository variable read by every run of every branch, so a flip relocates
CI **for every concurrent worker**, not just yours. Treat it as the shared resource
it is:

- **Serialise the write** behind whatever lock your workers already coordinate on,
  and **log it** with the prior value, the new value, what drove it, and the
  evidence. A flip nobody can attribute is a flip nobody can undo confidently.
- **Re-read after writing.** A write helper that probes-then-creates-or-updates can
  fail partially, so an exit code alone does not establish that the value changed.
- **Do NOT flip back while another worker has fallback work in flight** — that
  returns their queued jobs to dead capacity.
- **Setting the variable is not a stop.** It relocates CI *and* (in an automated
  setup) authorises a retry pass over eligible runs. Being a mode change, it is the
  wrong tool for "make it stop"; see §11.7.
- **Once the watcher acts, the variable is watcher-owned.** A hand-set value
  survives at most one tick. Do not hand-fight it — use the kill switch.

### 11.2 Ship report-only first, and encode the posture in the metric NAME

Deploy the watcher computing every decision and performing none, and observe it for
a period before enabling acting (§8.8 is how to make that structurally sound).

**Two metric NAMES over two filters — `FlipApplied` and `FlipSuppressed` — not one
metric with a `posture` DIMENSION.** A metric filter's dimensions are fixed at synth
time, so a posture dimension would have to be one value for both postures and would
collapse them into one series. The observation period exists to compare "what would
have happened" with "what happened"; a series that cannot separate the two answers
nothing at all.

### 11.3 Prefer LOG-DERIVED metrics over a metric-put permission

Emit exactly ONE structured record per tick and derive every metric from it with log
metric filters. Grant the execution role **no** metric-put permission. Two reasons,
and the second is the one that matters:

1. The metric-put action has **no resource-level permissions** — it can only be
   granted on `*`. The single wildcard grant in your whole stack would belong to the
   one component that acts on its own initiative.
2. **A log-derived metric and the log line an operator reads during an incident are
   the SAME artifact**, so the report-only evidence and the production alarm cannot
   disagree: if the metric is empty, the record is absent, and both say the same
   thing. With a separate metric API the record can be PRESENT and the metric SILENT
   — and *the alarm that never fires looks exactly like the system that never
   misbehaves*.

Filter-pattern details that decide whether any of this works:

- **If the record carries a text prefix before its JSON payload, a JSON filter
  pattern matches NOTHING.** MEASURED. Whether you have that shape depends on your
  log formatter: a formatter that renders only the message and drops structured
  extras forces the fields to ride INSIDE the message. Use TERM/substring patterns
  whose terms are byte-exact substrings of the RENDERED line.
- **Generate the filter terms with the SAME serialiser the emitter uses.** A
  hand-written `"key":"value"` matches nothing if the serialiser emits
  `"key": "value"`. Build each term by serialising a one-key object and stripping
  the braces, so the separators cannot drift. Import the terms into the IaC from the
  emitter's own module, so a field rename fails synth instead of shipping an inert
  alarm.
- **Substring matching has no negation.** A term over an array (`"ids": [`) matches
  the EMPTY array too, so key a metric on a BOOLEAN flag rather than on a list.
- **Every declared field must be present in every record from the start**, at a
  typed default, so a tick that died halfway still has the shape every filter
  expects. A field that appears only on the happy path is a term that silently
  matches nothing on the unhappy one.
- **Booleans must render `true`/`false`, never `null`** — `null` matches neither
  term, so a live tick that crashed before its write must still render
  `"write_performed": false`. That is what keeps the applied-flip metric EXACT: a
  failed flip is never counted as one.
- **Reset accumulating lists per record.** A reused execution container makes a
  shared list report the previous tick's retries.
- **State the field set EXPLICITLY** rather than deriving the record from it (or it
  from the record). The equality between "what the record declares" and "what the
  filters address" is the anti-drift bond; derive either side from the other and it
  becomes true by construction and stops being an assertion.
- **Emit from a `finally`, and make the emitter TOTAL.** An exception raised while
  emitting would REPLACE the original failure, losing both the diagnosis and the
  record; degrading to silence is worse, because the heartbeat alarm reads "no
  datapoint" as "the watcher is not running". The fallback keeps the marker
  (heartbeat intact) and flags the tick as failed (it pages), carrying nothing from
  the record.
- **Make the record's marker distinctive enough that no other line in the log group
  contains it as a substring**, or the heartbeat over-counts and a real outage
  becomes invisible.

### 11.4 If you relocate CREDENTIALED jobs, bound the relocation by PROPERTY

A deploy job holds credentials, so making its execution environment selectable by a
repository VARIABLE means anything with write access to that variable can relocate a
credentialed job. The reference implementation initially pinned those jobs to hosted
runners with a NEGATIVE guard ("these jobs are not switchable"), which had a real
cost: a default-branch push could never go green during an outage, so a red trunk
became routine and therefore unreadable.

The better answer is to relocate them but bound WHERE, with **positive** guards:

- the credentialed jobs may switch **only to an EPHEMERAL runner of the pinned
  project** — hosted remains the resolved default, and the only alternative the
  variable can express is one build per job, torn down with the job, on a label
  embedding the run id and attempt so nothing is reused across runs or attempts;
- **no job in the workflow may request a persistent runner host, an unmanaged
  self-hosted runner, a fleet, or a buildspec override.**

That answers the credential-blast-radius concern rather than dismissing it: no
credential outlives the job, and the credential file is written from repository
secrets exactly as on a hosted runner. What does NOT change is what the job DOES —
relocating a runner does not make a deploy less of a shared-state mutation.

And note the interaction with §10.2 escape 2: a reserved fleet persists cached data
across builds, which is precisely the property the ephemerality argument depends on
being absent. Choosing a fleet for memory reasons is also a security decision.

### 11.5 Give the watcher its OWN token, scoped minimally

| Permission | Level | Why |
|---|---|---|
| workflow runs / jobs / dispatch | read + write | list runs and jobs; re-run a refused run; dispatch the probe |
| repository variables | read + write | read and set the mode variable |
| metadata | read | usually mandatory for a fine-grained token |

**No contents, no secrets, no administration.** And note two couplings:

- **Do not reuse the token your tooling shares.** One kill-switch rung works by
  invalidating the watcher's token; if that is the shared token, the kill switch is a
  self-inflicted outage across everything.
- **The rate limit may be documented per USER, not per token.** MEASURED on the
  reference implementation: a steady tick costs at most 13 reads, i.e. ≤156/hour,
  about 3.1 % of a 5 000/hour limit — small, but on a shared token that 3.1 % is
  taken from every concurrent session.
- **Write access to the workflow-run surface is an infrastructure-mutation
  capability** for as long as any deploy gate is ref-unconditional (§9.2). The retry
  authorisation is what bounds it.
- The source credential's token (§3.2) needs *webhook administration* and often
  broad repository access — the WRONG shape here. Copy-pasting that recipe into this
  slot is the mistake this table exists to prevent.

### 11.6 Let the IaC declare ZERO secrets

Create the credential secret out of band and pass its **complete** resource
identifier as a stack input. With no secret resource declared, no redeploy,
property replacement, construct-id change, or stack deletion can destroy the
operator's token. (A declared secret whose replacement is forced creates a FRESH,
empty one — and the runtime then 401s on every call, which is §9.3's symptom
arriving by a different road.)

At synth, **refuse**: an absent value; a bare name; an identifier without the
random suffix; a wildcard; one naming a different account or region; and one that
looks like a TOKEN rather than an identifier — refuse that last one **without
echoing the value**, because pasting the token into the identifier slot is the
commonest mistake here. Requiring the complete identifier is not fastidiousness: it
lets the read grant name one exact resource instead of the wildcard a name-based
lookup produces.

Grant the read on that literal identifier and nothing else. Avoid the convenience
`grant_read` helper if it bundles extra actions — MEASURED on the reference
implementation, it adds a describe action as a PAIR.

Two prerequisites IaC cannot express, so write them in your runbook:

- a **resource policy on the secret** pinning the read to the watcher's execution
  role — nothing else bounds which of the account's principals can read the token;
- a **decrypt grant** if you used a customer-managed key. With the default service
  key none is needed; with a customer key and no grant **every tick fails** and
  nothing in the template can detect it.

### 11.7 Alarms — and the one everyone forgets

| Alarm | Fires when | Missing data | Why |
|---|---|---|---|
| **Heartbeat** (tick count) | fewer than 1 record in two consecutive periods, **or none at all** | **BREACHING** | The watcher has STOPPED |
| Flip applied | any live mode write | not breaching | CI has been relocated for every concurrent worker |
| Retry issued | any re-run issued | not breaching | The highest-blast-radius action it takes |
| Effect failed | 2 of 3 ticks completed with a failed effect | not breaching | Otherwise a tick that completed while an effect did not land is indistinguishable from a clean one, and the operator sees red runs beside a green watcher |
| Unhandled function errors | 2 consecutive | not breaching | Most likely a dead credential — and the only signal for the whole unhandled-crash class |

**The heartbeat is the one most easily forgotten and by far the most dangerous.** A
watcher that has silently stopped ticking produces no datapoints — and with missing
data treated as *not breaching*, the alarm **certifies a dead watcher as healthy**,
so nothing fires and the operator's belief that CI is being watched is simply false.
Treat missing data as **BREACHING**.

Note that there are TWO distinct silences and they need different mechanisms:

- **"never invoked"** — no datapoints exist at all ⇒ needs `TreatMissingData:
  breaching`;
- **"invoked but silent"** — the function ran and the filter matched nothing ⇒ needs
  the metric filter's zero DEFAULT VALUE, because a default cannot fill a period
  that has no log event to default.

**The suppressed-flip metric needs NO alarm.** During the observation period every
would-be flip suppresses, so an alarm on it pages continuously on the subsystem
working exactly as designed. It is the period's evidence: read the count.

Also: the unhandled-error alarm is **mandatory, not optional**, because a propagated
exception writes no record marker — so the effect-failed metric is blind to it while
the heartbeat still sees a datapoint (the record is emitted from a `finally`). Only
the runtime's own error metric sees that class.

**An alarm topic with no subscriber is not monitoring.** Subscribe a human before
enabling acting, and verify it.

### 11.8 The kill switch: three rungs, and the obvious one is not a stop

| Rung | Action | Effect | How you know it worked |
|---|---|---|---|
| **L1** | Disable the schedule | No further ticks. Cleanest: nothing is deleted, re-enabling resumes | The heartbeat alarm goes to ALARM — **expected**, and the confirmation |
| **L2** | Invalidate the credential's VALUE | Every tick raises before reaching the host. Works **only** because the token is read per invocation and never cached | The unhandled-errors alarm, and **only** that one (see §11.7) |
| **L3** | Redeploy without the acting flag | Keeps observing, performs nothing | Suppressed-flip datapoints resume; applied-flip stops |

Setting the mode variable is **not** on this list. It is a mode change that also
authorises a retry pass, and in the acting posture it is reconciled within one tick.

To remove the watcher entirely, redeploy without its opt-in flag. Nothing should be
retained — and your secret is untouched, because the stack never owned it (§11.6).

---

## 12. Verification checklist

### 12.1 What a report-only deployment CAN and CANNOT prove

| Can prove | Cannot prove |
|---|---|
| The **schedule** fires at the declared period (heartbeat datapoints at the expected rate) | The variable **WRITE** — no write is attempted, so the token's write scope, the confirm-read, and the post-write anchor are all unexercised |
| The **read path** end to end (every record carries the observed mode and its timestamp) | The **retry** path — no re-run is issued, so §9.2's authorisation is exercised only as a census |
| The **decision on real data** (target mode, whether a change was wanted, and the reason) | The **probe dispatch** — no probe runs, so the probe workflow's own hosted pin is unexercised in flight |
| The **evidence fence** (the floor, runs considered, runs after fence — which separates "nothing was wrong" from "the fence discarded everything") | Therefore: the whole **flip-forward → relocate → recover** round trip |
| The **exclusion census** — how often a field the host's reference does not guarantee is actually absent, and how much of the listing the deploy bound removes | |
| **Telemetry itself** — every declared field present, booleans rendering as booleans, every filter matching a real line | |

The census is the part most worth designing deliberately: count exclusions over the
runs as **FETCHED**, not over the fenced survivors, because the two populations are
close to disjoint (§9.1) and a census over the survivors reports a reassuring number
computed from the wrong set. Make it a CENSUS, not a partition — a run can be
excluded for several reasons at once, and partitioning hides the overlaps that make
an exclusion robust. And put at least one counted run OUTSIDE the fence in the test
fixture, or a counter wired to a constant reports the reassuring value whether or
not it works.

### 12.2 The executable checklist

1. **Phase 0 go/no-go.** Dispatch the scratch workflow while hosted capacity is
   refusing. PASS = at least one job with a fallback-prefixed label AND a non-empty
   runner name AND executed steps. On a hang: **stop**; the design collapses to
   paying the overage.
2. **Default-arm no-op.** With the variable UNSET, one full pipeline run is
   byte-identical in runner attribution to before the switch merged. Assert in a
   test that the false arm's literal equals the pin it replaced.
3. **Relocation.** Set the variable, re-read it, then **push a new commit to a
   branch** (do NOT re-run, do NOT dispatch the pipeline — §9.2). Confirm every job
   carries a fallback-prefixed label WITH a non-empty runner name.
4. **Body parity, not just dispatch.** The relocated run must be **GREEN**. Record
   which job bodies you actually measured; a toolchain-only pilot job covers the
   toolchain, not the body. Pin the project, image and size equal between the pilot
   and the real pipeline, or the pilot's evidence does not transfer.
5. **Sizing.** Read each job's memory headroom from the **build-level utilization
   metrics** (§10.5) — not wall clock, not the job log. Confirm the runner project's
   build timeout exceeds your longest job timeout.
6. **Classification.** Capture per-job-with-steps detail for one job of each shape
   you can produce (A, B, C, D per §6.2) and check your classifier's verdict on each.
   The (D)-vs-(B) pair is the one that matters most.
7. **Probe guards.** Run the parsed-workflow census and the equality pin — then
   **prove the negatives**: a fixture copy of the switching expression must RED the
   equality test, and an empty workflow glob must RED the census's liveness floor.
8. **Watcher in report-only** for a full period — ideally spanning a real outage,
   otherwise a synthetic evidence replay through the pure decision function. Read
   the suppressed-flip count and the exclusion census.
9. **Alarms.** Confirm each fires. Prove the heartbeat by **disabling the schedule**
   and watching it go to ALARM; that transition is the confirmation, not a
   malfunction.
10. **Subscriber.** Confirm a human actually receives the topic.
11. **Only then enable acting** — and expect the mode variable to become
    watcher-owned from that moment (§11.1).

### 12.3 Evidence discipline

State the terminal status with the run id, the conclusion, and the commit it ran
against. When the run was relocated, additionally quote the runner attribution —
fallback labels **with non-empty runner names** — so "green" cannot be claimed from
a hosted run that never happened. And disclose every job of a merged run that did
NOT execute, with its exit condition: a run whose relocatable jobs are green and
whose deploy stage never ran leaves the change **deployed-unverified**, and that
should stay visible until a later run exercises the stage.
