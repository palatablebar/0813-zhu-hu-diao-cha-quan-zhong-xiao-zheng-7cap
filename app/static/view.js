import {element, pretty} from './client.js';

const labels = {READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓', RELEASED:'可签发', DEFERRED:'暂缓', ISSUED:'已发布'};
const headers = ['业务分组', '输入行', '计算值', '参考值', '判定'];

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

export function snapshot(report, selected, stage, issued = null, batch = null) {
  const stats = report.intake;
  const plan = report.release;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  document.querySelector('[data-metric="released"]').textContent = plan ? plan.totals.released_groups : '—';
  document.querySelector('[data-metric="deferred"]').textContent = plan ? plan.totals.deferred_groups : '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>element('td',value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else {
    head.append(...headers.map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
    }
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  const shown = picked ? picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status} : stats.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
  document.querySelector('#counts').textContent = report.balance ? `行数 ${report.balance.accounted}/${report.balance.input} · ${report.balance.ready} 组通过` : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
  delivery(plan, issued ?? report.releases, batch);
}

const checkLabels = {
  input_split: '输入行 = 采信+隔离+忽略',
  records_split: '采信行 = 发布记录+暂缓记录',
  groups_split: '业务组 = 可签发+暂缓',
  line_split: '源行逐组归集齐全',
  isolation_split: '隔离行逐组归集齐全',
  replay_split: '重复回放逐组归集齐全',
  deferred_has_reason: '暂缓组均带原因',
  release_only_verified: '发布包只含已核对记录',
};

export function delivery(plan, issued, batch) {
  const table = document.querySelector('#delivery-rows');
  const checks = document.querySelector('#delivery-checks');
  const counts = document.querySelector('#delivery-counts');
  const bundle = document.querySelector('#bundle');
  table.replaceChildren();
  if (!plan) {
    counts.textContent = '进入运行对账阶段后汇总';
    checks.textContent = '';
    checks.removeAttribute('data-failure');
    bundle.hidden = true;
    return;
  }
  bundle.hidden = !batch;
  if (batch) bundle.href = `/api/runs/${batch}/bundle`;
  const head = element('tr');
  head.append(...['业务分组', '结论', '发布版本', '采信行', '隔离行', '原因'].map(title => element('th', title, {scope:'col'})));
  const body = table.createTBody();
  const versions = new Map((issued || []).map(item => [item.case, item]));
  for (const group of plan.groups) {
    const tr = body.insertRow();
    tr.insertCell().textContent = group.case;
    tr.insertCell().append(badge(group.status));
    const version = versions.get(group.case);
    const link = version
      ? element('a', `v${version.version}`, {href:`/api/releases/${version.id}`})
      : element('span', group.status === 'RELEASED' ? '待执行' : '—');
    tr.insertCell().append(link);
    tr.insertCell().textContent = group.records ? group.records.length : group.counts.accepted;
    tr.insertCell().textContent = group.counts.isolated;
    tr.insertCell().textContent = group.reasons.length ? group.reasons.join(' · ') : '—';
  }
  table.createTHead().append(head);
  const {totals} = plan;
  counts.textContent = `可签发 ${totals.released_groups} 组 / ${totals.released_records} 行 · 暂缓 ${totals.deferred_groups} 组 / ${totals.deferred_records} 行`;
  const lines = Object.entries(plan.checks).map(([key, ok]) => `${ok ? '✓' : '✗'} ${checkLabels[key] || key}`);
  const orphan = plan.unassigned;
  if (orphan && (orphan.isolated || orphan.ignored)) {
    const reasons = Object.entries(orphan.reasons).map(([key, value]) => `${key}×${value}`).join('、');
    lines.push(`未归组隔离 ${orphan.isolated} 行${reasons ? `（${reasons}）` : ''} · 忽略 ${orphan.ignored} 行`);
  }
  checks.textContent = lines.join('　');
  checks.dataset.failure = String(!plan.balanced);
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
