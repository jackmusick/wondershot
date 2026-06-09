export const meta = {
  name: 'wondershot-ui-review',
  description: 'Vision-critique Wondershot UI screenshots against tokens.css + wonderblob reference',
  phases: [{ title: 'Critique' }]
};

// args: { shots: string[] }  — absolute or repo-relative PNG paths to review.
const shots = (args && args.shots) || [
  'artifacts/ui/shell-dark.png',
  'artifacts/ui/sidebar-dark.png',
  'artifacts/ui/header-dark.png'
];

const FINDINGS = {
  type: 'object',
  required: ['shot', 'pass', 'findings'],
  properties: {
    shot: { type: 'string' },
    pass: { type: 'boolean' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'area', 'issue', 'fix'],
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
          area: { type: 'string' },
          issue: { type: 'string' },
          fix: { type: 'string' }
        }
      }
    }
  }
};

phase('Critique');
const results = await parallel(shots.map((shot) => () =>
  agent(
    `Read the screenshot at ${shot}. Also read src/lib/styles/tokens.css and, if present, ` +
    `the reference artifacts/ui/ref/wonderblob-shell.png. Critique the screenshot for ` +
    `fidelity to the design language: correct two-plane backgrounds (sidebar #141416, ` +
    `content #29292c), 6px radii, 28px control heights, --text-base/--text-small ` +
    `typography, hover/selected states (inset 2px accent bar), spacing scale, and focus ` +
    `rings. Report concrete, fixable findings. Set pass=false if any blocker/major exists.`,
    { label: `critique:${shot.split('/').pop()}`, schema: FINDINGS, agentType: 'general-purpose' }
  )
));

const reviewed = results.filter(Boolean);
const failures = reviewed.filter((r) => !r.pass);
log(`UI review: ${reviewed.length} shots, ${failures.length} need work`);

// Workflow result (implicit return by runtime)
{ reviewed, failures };
