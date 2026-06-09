export const meta = {
  name: 'wondershot-ui-review',
  description: 'Vision-critique Wondershot UI screenshots against tokens.css + wonderblob reference',
  phases: [{ title: 'Critique' }]
};

// args: { shots: Array<string | { path, kind?, description? }> }
//   kind: 'shell'     -> full two-plane layout; evaluate sidebar vs content tiers.
//   kind: 'component' -> isolated single component; the surrounding dark area is just
//                        the empty page background and MUST NOT be flagged as a missing
//                        pane / missing two-plane separation.
// A bare string is treated as a 'shell' shot for backwards compatibility.
const REF = 'tests-ui/ref/wonderblob-shell.png';

const raw = (args && args.shots) || [
  { path: 'artifacts/ui/shell-dark.png', kind: 'shell' },
  { path: 'artifacts/ui/sidebar-dark.png', kind: 'component', description: 'isolated LibrarySidebar only' },
  { path: 'artifacts/ui/header-dark.png', kind: 'component', description: 'isolated CaptureHeader only' }
];
const shots = raw.map((s) => (typeof s === 'string' ? { path: s, kind: 'shell' } : { kind: 'shell', ...s }));

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
const results = await parallel(shots.map((shot) => () => {
  const scope = shot.kind === 'component'
    ? `This is an ISOLATED COMPONENT screenshot (${shot.description || 'a single component'}). ` +
      `Evaluate ONLY this component. The dark area around or beside it is the empty page ` +
      `background and is EXPECTED — do NOT flag a "missing two-plane layout", a missing sidebar/` +
      `content pane, or controls that live in other components. Judge only this component's own ` +
      `background, radii, control heights, typography, spacing, and any states it actually shows.`
    : `This is a FULL SHELL screenshot. Evaluate the complete two-plane layout: the sidebar plane ` +
      `(--bg-sidebar #141416) and the content plane (--bg-content #29292c) must be visibly distinct, ` +
      `plus radii, control heights, typography, spacing, hover/selected/focus states where present.`;
  return agent(
    `Read the screenshot at ${shot.path}. Also read src/lib/styles/tokens.css and the reference ` +
    `${REF} if it exists. ${scope} ` +
    `Design language: 6px radii (--radius), 28px control heights, --text-base (13px) / --text-small ` +
    `(11.5px) typography, selected state = --bg-selected with an inset 2px --accent left bar, hover = ` +
    `--bg-hover, focus = 2px --accent ring. IMPORTANT: rest-state screenshots usually do not exercise ` +
    `hover/selected/focus — treat an unexercised state as "unverified", NOT as a defect, and do not ` +
    `lower pass for it. Report concrete, fixable findings. Set pass=false ONLY if a real blocker or ` +
    `major defect is actually visible within this shot's scope.`,
    { label: `critique:${shot.path.split('/').pop()}`, schema: FINDINGS, agentType: 'general-purpose' }
  );
}));

const reviewed = results.filter(Boolean);
const failures = reviewed.filter((r) => !r.pass);
log(`UI review: ${reviewed.length} shots, ${failures.length} need work`);

// Workflow result (implicit return by runtime)
({ reviewed, failures });
