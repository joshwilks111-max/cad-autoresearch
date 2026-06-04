export const meta = {
  name: 'prelanding-review',
  description: 'Pre-landing review of the drawing-assets branch: correctness + testing + maintainability + red-team',
  phases: [
    { title: 'Review', detail: 'parallel reviewers over the diff' },
    { title: 'Verify', detail: 'adversarially verify each finding is real' },
  ],
}

const REPO = 'C:/Users/joshw/CAD Autoresearch/cad-autoresearch'

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['lens', 'findings'],
  properties: {
    lens: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'confidence', 'file', 'summary'],
        properties: {
          severity: { type: 'string', enum: ['CRITICAL', 'INFORMATIONAL'] },
          confidence: { type: 'integer' },
          file: { type: 'string' },
          line: { type: ['integer', 'null'] },
          summary: { type: 'string' },
          motivating_line: { type: 'string', description: 'verbatim code line(s) that triggered the finding' },
          fix: { type: 'string' },
        },
      },
    },
  },
}

const LENSES = [
  {
    key: 'correctness',
    prompt: `You are reviewing for CORRECTNESS BUGS in a Python CAD-harness change. The highest-risk
file is loop/answer_key_guard.py — a context manager that MOVES answer-key files (os.replace)
out of a repo during a worker spawn and restores them in a finally. Read these files in full:
  ${REPO}/loop/answer_key_guard.py
  ${REPO}/loop/policies.py  (the hidden_answer_keys() wrapping around subprocess.run)
  ${REPO}/drawing_extract.py  (the _backend_claude --model pin + 420s timeout; the _GEMINI_MODELS list)
  ${REPO}/orchestrator.py and ${REPO}/watcher.py  (the restore_orphaned startup sweep)

Hunt specifically for: data-loss windows (a key moved out but not restored on some path),
os.replace cross-device failures, the finally-restore missing an exception path, concurrent
worker races on the staging dir, a path-traversal in the relative-path rejoin, the guard
hiding MORE or FEWER files than the 3 documented classes. Quote the exact motivating line for
every finding. Only report a finding if you can quote the code that proves it.`,
  },
  {
    key: 'testing',
    prompt: `You are reviewing TEST QUALITY. Read:
  ${REPO}/tests/test_answer_key_guard.py
  ${REPO}/evals/test_fixtures_discovered.py
  ${REPO}/evals/drawing_read_ab.py
Check: do the guard tests actually prove the leak is closed (not just that files move)? Does the
glob test prevent the false-green bug (a new empty fixture must FAIL, not be ignored)? Are there
meaningful assertions (not just assertNotNone)? Any test that passes vacuously? Any missing edge
case that would let a real bug through? Quote the motivating line for each finding.`,
  },
  {
    key: 'maintainability',
    prompt: `You are reviewing MAINTAINABILITY of this Python change. Read the changed files under
${REPO}/loop/, ${REPO}/evals/, and ${REPO}/drawing_extract.py. Check: hardcoded paths that should
be derived, magic numbers without explanation, duplicated logic, a module that will rot, unclear
naming, a comment that lies about the code. This repo values terse code that matches surrounding
style. Quote the motivating line for each finding.`,
  },
  {
    key: 'redteam',
    prompt: `You are a RED TEAM reviewer. The change adds a security guard (answer_key_guard.py) that
hides eval answer-keys from a spawned worker. Your job: find what a normal review MISSES. Read
${REPO}/loop/answer_key_guard.py and ${REPO}/loop/policies.py. Think adversarially: can the worker
STILL reach the answer keys despite the guard? (e.g. the guard only wraps the claude -p spawn —
what about a subagent the worker spawns that outlives the with-block? what if the worker reads via
an absolute path it learned elsewhere? what if os.replace fails silently? what about the .gitignored
.best_score that the guard moves — does moving it break the ledger mid-run?) Also: does the 420s
timeout or the gemini model list introduce a regression? Quote the motivating line for each finding.`,
  },
]

phase('Review')
const reviewed = await pipeline(
  LENSES,
  (lens) => agent(lens.prompt, {
    label: `review:${lens.key}`,
    phase: 'Review',
    schema: FINDINGS_SCHEMA,
    agentType: 'Explore',
  }),
  // verify each finding adversarially as soon as its lens completes
  (review) => parallel((review.findings || []).map((f) => () =>
    agent(
      `Adversarially verify this code-review finding. Try to REFUTE it. Read the actual file and
quote the real code. A finding is REAL only if the quoted code genuinely exhibits the problem.
Default to refuted=true if the motivating line doesn't support the claim or the code is actually fine.

Finding: ${JSON.stringify(f)}
Repo root: ${REPO}`,
      {
        label: `verify:${f.file}:${f.line || '?'}`,
        phase: 'Verify',
        schema: {
          type: 'object',
          required: ['refuted', 'reason'],
          properties: {
            refuted: { type: 'boolean' },
            reason: { type: 'string' },
            corrected_severity: { type: ['string', 'null'] },
          },
        },
      }
    ).then((v) => ({ ...f, lens: review.lens, verdict: v }))
  )),
)

const confirmed = reviewed.flat().filter(Boolean).filter((f) => f.verdict && !f.verdict.refuted)
return {
  total_raw: reviewed.flat().filter(Boolean).length,
  confirmed_count: confirmed.length,
  confirmed,
}
