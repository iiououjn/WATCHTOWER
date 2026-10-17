// The hosted demo: a made-up run that loops forever, shaped exactly like /api/state. Nothing here reads a real tower.
(function () {
  var CYCLE = 130;
  var STAGES = [   // [start second, status, floor, awake agents, what the audit log says]
    [0, 'running', 'f1', ['f1.lead', 'f1.worker', 'f1.hr'], 'research: reading the idea, searching the web'],
    [14, 'running', 'f2', ['f2.architect', 'f2.coder', 'f2.hr'], 'dev: architect plans, developer writes app.py'],
    [36, 'running', 'f3', ['f3.lead', 'f3.hr'], 'build: packaging the app'],
    [50, 'running', 'f4', ['f4.qa', 'f4.lead', 'f4.hr'], 'qa: running tests and the form check'],
    [66, 'running', 'f5', ['f5.gate', 'f5.auditor', 'f5.lead', 'f5.dev_gate'], 'oversight: gate review and security scan'],
    [80, 'paused', 'csuite', ['ceo', 'cpo'], 'sign-off requested: waiting for the owner'],
    [98, 'running', 'f4', ['f4.lead', 'f4.hr'], 'deploy: building the image, starting the container'],
    [116, 'done', null, [], 'done: app deployed on 127.0.0.1:8100']
  ];
  function stageAt(s) { var cur = STAGES[0]; for (var i = 0; i < STAGES.length; i++) if (s >= STAGES[i][0]) cur = STAGES[i]; return cur; }
  window.WT_DEMO_STATE = function (t) {
    var c = Math.floor(t / CYCLE) % 90 + 1, s = t % CYCLE, st = stageAt(s), idx = STAGES.indexOf(st), live = st[1] === 'running' || st[1] === 'paused';
    var iso = new Date(t * 1000).toISOString(), audit = [], seq = c * 100;
    for (var i = 0; i <= idx; i++) { audit.push({ seq: ++seq, ts: new Date((t - s + STAGES[i][0]) * 1000).toISOString(), job_id: 'demo-' + c, actor: 'bus', action: 'board.note', detail: STAGES[i][4] }); }
    return {
      jobs: [
        { id: 'demo-' + c, status: st[1], prompt: 'Build a todo app with priorities and due dates (demo run ' + c + ')', error: null, updated_at: iso, floor: st[2], awake: st[1] === 'running' ? st[3] : [] },
        { id: 'demo-' + (c - 1), status: 'done', prompt: 'Build a guestbook with moderation (earlier demo run)', error: null, updated_at: iso, floor: null, awake: [] }
      ],
      approvals: st[1] === 'paused' ? [{ id: c, job_id: 'demo-' + c, kind: 'signoff', summary: 'Title: Todo app\nFiles: app.py, store.py, test_store.py\nTests: 12 passed, security scan clean', created_at: iso }] : [],
      audit: audit.slice(-50), budgets: live ? [{ job_id: 'demo-' + c, used_tokens: Math.round(s * 310), max_tokens: 60000, used_seconds: Math.round(s * 4) / 1, max_seconds: 1800 }] : [],
      deployments: [{ name: 'todo-app', job_id: 'demo-' + (s >= 106 ? c : c - 1), port: 8100, status: 'active', created_at: iso, ended_at: null }],
      chain_ok: true, now: iso
    };
  };
})();
