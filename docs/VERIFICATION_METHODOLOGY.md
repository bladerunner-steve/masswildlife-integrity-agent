# Verification methodology

This document defines what the verifier checks, against which adversary, under which trust assumptions, and
how it decides between its three outcomes. The implementation is `src/mwia/verify/`. Every check named here is a
finding code in `src/mwia/verify/findings.py`, so a badge's findings can be traced back to this text.

## 1. What is being protected

A **run** is one execution of the agent: PR0 (plan) → PR1 (request) → PR2 (response) → PR3 (filter) →
PR4 (database) → PR5 (completion), closed by a **seal**. We want a reader of the badge to be able to rely on four claims:

1. **Integrity:** the recorded steps and their evidence are exactly what was produced at the time.
2. **Plan conformance:** the run executed the steps its signed plan declared, in order, with the declared code.
3. **Policy compliance:** what the run did (the request it sent, the records it accepted and wrote, the DB
   account and operations it used) stays within the policy, and the policy itself matches trusted pins.
4. **Evidence sufficiency:** enough fresh, consistent evidence was kept to support the run's own claims.

## 2. Adversary model

The adversary may **control any strict subset of the agent's stages** (for example, alter what M1 requests,
make M3 skip a step, inflate the counts M4 reports, or drop evidence before signing), and may have **write access
to the vault afterwards** (alter, delete or insert files, rewrite the ledger). The adversary does **not** control
**both** the notary's private key **and** the offline verifier: at least one of them is out of reach.

The attacks form a ladder, each step stronger than the last:

| Attack | What the adversary does | What defeats it |
|---|---|---|
| **Naive tamper** | changes an evidence object, leaves the receipt as is | the evidence no longer hashes to the value its receipt recorded (A) |
| **Log rewriting** | changes the evidence **and** the hash in the receipt, recomputes `receipt_hash` | the receipt's signature no longer matches its body (A) |
| **Forward recompute** | rebuilds the chain from the tampered step on (hashes, links, Merkle root, seal) and signs with a key of its own | the signatures come from an untrusted key (A) |
| **Key forgery** | re-signs the whole run with a key that is not one of the trusted notary keys | untrusted key (A) |
| **Replay** | copies a receipt from another run into this run | the receipt's run id and place no longer match, the chain breaks, and its nonce and hash already belong to another run (A) |
| **Rollback / deletion** | deletes the newest run and rewrites the ledger so the vault looks consistent | the external anchor names a seal and a ledger position the vault no longer has (A, anchors) |
| **Signed but unauthorized** | a compromised or misconfigured agent sends an out-of-policy request (another place or project, location parameters, a window over 24 h), and the notary signs it, since the notary is a witness, not a policy engine | the policy is re-evaluated from the signed plan and the verifier's own pins (B) |
| **Plan deviation** | skips, reorders or adds steps, all validly signed | executed sequence differs from the declared one (B) |
| **Omission / inconsistency** | drops a raw page or decision list before signing, or signs counts that don't add up | mandatory-evidence and reconciliation checks (C) |

The last three rows are the cases where cryptographic verification alone gives **false assurance**: every
signature is valid, so configuration A says VERIFIED. Measuring how often layers B and C turn those into
the right verdict is the research question.

## 3. Trust assumptions

- **Notary key secrecy.** The private key is encrypted (PKCS#8 + passphrase), readable only by its owner, and
  loaded only by the notary process. Trust in a key is expressed by its public key being in `keys/public/`. A
  retired key is not trusted for signatures dated after its retirement.
- **Verifier integrity.** The verifier code, `keys/public/` and `config/verifier.yaml` are under the reader's
  control. The verifier never imports agent code and never reads MySQL; a test enforces both. It reads the vault
  read-only.
- **Pins.** `config/verifier.yaml` pins the project (46777, its slug, scope place 141552), host, endpoint, method,
  window limits, DB user, allowed tables and operations, forbidden parameters and fields, and the declared step
  sequence. The signed policy snapshot must be no weaker than these.
- **Anchors outside the vault.** The anchor log is only as strong as the place it is kept. A separate git repo is
  the default; pushing it, or emailing it, to somewhere the vault's owner can't rewrite makes rollback detection robust.
- **Clocks.** Timestamps come from the agent's machine. Freshness checks assume that clock is roughly correct.

## 4. The three layers

### A. Cryptographic (`crypto.py`)

- Each receipt and the seal verify with a trusted Ed25519 key; `receipt_hash = SHA-256(JCS(body))` recomputes
  (RFC 8785 canonical JSON); the body passes the strict receipt schema.
- Each receipt lies under its own run and step key, and its nonce and hash are not found in any other run (replay).
- The chain is rebuilt from `prev_hash` links starting at PR0: no fork, no orphan, and PR0 links to the previous
  run's seal (or 64 zeros for the first run). Every `spec_hash` equals PR0's hash.
- Every referenced evidence object exists and re-hashes to its recorded hash. `out_hash` equals the step's
  primary output evidence, and `in_hash` equals the previous step's `out_hash`.
- Every module's `agent_id` (a measurement over its source files, the tool manifest, the policy and the key id)
  equals the value PR0 declared.
- The seal verifies, and its Merkle root (RFC 6962), receipt count, head and `prev_seal_hash` match the chain.
- The vault ledger replays cleanly for this run's objects (and has no global break), and the anchors agree with
  the vault (no anchored seal missing, ledger not truncated or rewritten). A seal that was never anchored, and a
  run with no seal at all (a truncated trace, see §6), are *insufficient* rather than *failed*.

### B. Policy (`policy.py`)

The policy is taken from the **signed PR0 snapshot**, and checked against the policy file bytes stored as PR0
evidence, never against the file on disk today.

- The snapshot is consistent and no weaker than the pins.
- The plan's window is at most 24 h + grace.
- The recorded request (PR1) and **every fetched page** (PR2, including the page's actual URL, which must match
  its recorded parameters) use the allowed host, endpoint and method, the pinned project, no forbidden or unknown
  parameter, no private field, the plan's window and the required ordering.
- No receipt for PR1, PR2 or PR4 records a violation (for example, a request the gate blocked).
- PR4 ran as the pinned user, on an allowed table, with allowed operations only (SELECT only in a dry run).
- The executed step sequence equals the declared one. An unsealed run that stopped part-way through its plan is
  treated as incomplete (layer C), not as a deviation.
- No observation outside the scope place or the window was accepted, and nothing that wasn't accepted reached the
  database. These checks run only when the evidence they need is present; missing evidence is layer C's concern.

### C. Evidence (`evidence.py`)

Every step left a receipt, and each carries its mandatory evidence (PR0 plan and policy, PR1 request, PR2 one raw
page per recorded page plus a summary, PR3 decision list, PR4 DB readback, PR5 reconciliation). The raw pages
match what PR2 says about them and form a gap-free keyset sequence that ran to the end. The counts reconcile:
`total_results ≥ fetched`, `fetched = accepted + rejected`, `accepted = inserted + updated + skipped`, and the
PR3/PR4/PR5 numbers agree with the evidence. The readback contains every accepted record and matches what was
written. Responses were fetched after the window closed and within the allowed lag. Accepted observations fall
inside the window. PR5's status follows from all of this.

Every layer C finding is *insufficient*, never *failed*: missing or self-contradictory evidence means the run
can't be vouched for, but it doesn't by itself prove tampering.

## 5. Decision rules

Each finding carries a layer, a code, a severity (`fail` or `insufficient`) and, where possible, the step and
module. For a chosen configuration (A, B or C), only that configuration's layers run, so a configuration can
only ever report what its layers can see.

| Outcome | Rule |
|---|---|
| **VERIFICATION FAILED** | at least one `fail` finding |
| **INSUFFICIENT EVIDENCE** | no `fail`, at least one `insufficient` |
| **VERIFIED WITHIN SCOPE** | no findings |

**Localization:** the reported failure is the earliest step, in step order, with a failing finding, together
with its module and a plain-language message. Each verdict records the configuration that produced it.

## 6. Decisions recorded with the author

- **Truncated trace** (receipts but no PR5/seal): *insufficient*. A missing seal can be a crash and doesn't by
  itself prove tampering. Suppressing the newest seal is caught by the anchors once a later run exists.
  Configurable in `config/verifier.yaml`.
- **The verifier pins its own trust values** in addition to the vault, keys and anchors.
- **Layer C never returns FAILED.**
- **A run the policy gate blocked is red:** the agent behaved correctly, but someone attempted a forbidden query.
- **A red or amber run doesn't count as covering its window**, so the next run re-reads it (within the 24 h cap).

## 7. Non-goals

- **Factual correctness.** A green badge doesn't mean the observations, identifications or locations are right,
  or that iNaturalist's data is complete.
- **Hidden reasoning.** The modules are deterministic code. Nothing here inspects, or claims to explain, the
  reasoning of people or models behind the data.
- **Tamper-proofing.** The guarantee is detection, not prevention (see the README's honest limits).
- **An adversary holding both the notary key and the verifier.** That is outside the threat model by assumption.

## 8. Evaluation

`eval/` generates independently labelled traces for every row of the attack table above (plus clean runs,
unreconcilable counts and truncated traces) and measures each configuration's verdicts. The definitions of
false-assurance rate, precision/recall/F1, false alarms, insufficient-evidence recognition and localization
accuracy are in `eval/metrics.py`. The measured results and their threats to validity are in
`eval/results/summary.md`.
