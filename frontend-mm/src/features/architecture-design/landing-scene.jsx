// A small picture of a landing zone being drawn: the organisation, three groups, and the accounts under them.
// One motion, the lines drawing in. With reduced motion the picture is already there.

const GROUPS = [
  { name: 'Security', accounts: ['Log archive', 'Audit'] },
  { name: 'Infrastructure', accounts: ['Network', 'Shared services'] },
  { name: 'Workloads', accounts: ['Production', 'Development'] },
];

export default function LandingScene() {
  return (
    <div className="lz-scene" role="status">
      <p className="lz-scene-status">Designing the landing zone…</p>
      <div className="lz-scene-board" aria-hidden>
        <p className="lz-scene-root">Organisation</p>
        <div className="lz-scene-groups">
          {GROUPS.map((group) => (
            <div key={group.name} className="lz-scene-group">
              <p>{group.name}</p>
              <ul>
                {group.accounts.map((account) => <li key={account}>{account}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
