// Snapshot of Actual data for the Money Ladder page (money-ladder.js), written
// to JSON. Run as a child process by money-ladder.js when the snapshot is stale
// or the page asks for a refresh.
//
// Raw per-month totals only: the page picks which income categories, spending
// groups and cash accounts count, so changing those never needs a re-export.
const api = require('@actual-app/api');
const fs = require('fs');
const { openBudget, closeBudget } = require('./utils');

const OUT = process.env.LADDER_SNAPSHOT || '/data/snapshot.json';
const MONTHS = 12;

// Same emoji naming scheme as networth-export.js.
const EMOJI_TYPES = [
  ['🏦', 'Cash'], ['💹', 'Investments'], ['👴', 'Retirement'], ['🏥', 'HSA'],
  ['🏠', 'Real estate'], ['🏚', 'Mortgage'], ['🚗', 'Vehicles'], ['💳', 'Credit cards'],
];
const accountType = (name) =>
  (EMOJI_TYPES.find(([e]) => name.startsWith(e)) || [, /\bloan\b/i.test(name) ? 'Loan' : 'Other'])[1];

(async () => {
  const tz = process.env.TZ || 'America/New_York';
  const today = new Date().toLocaleDateString('en-CA', { timeZone: tz });
  // The last MONTHS full months, oldest first, plus the current partial month.
  const [y, m] = today.split('-').map(Number);
  const months = [];
  for (let i = MONTHS; i >= 0; i--) {
    const d = new Date(Date.UTC(y, m - 1 - i, 1));
    months.push(d.toISOString().slice(0, 7));
  }

  await openBudget();
  const accounts = await api.getAccounts();
  const groups = await api.getCategoryGroups();
  const { data: txns } = await api.runQuery(
    api.q('transactions')
      .select(['account', 'date', 'amount', 'category', 'transfer_id'])
      .options({ splits: 'inline' })    // children carry the categories
  );
  await closeBudget();

  const catInfo = {};
  for (const g of groups) for (const c of g.categories) catInfo[c.id] = { group: g.name, name: c.name, income: !!g.is_income };
  const byId = Object.fromEntries(accounts.map((a) => [a.id, a]));

  const balance = {};
  const income = {};     // category -> month -> dollars
  const spending = {};   // group -> month -> dollars (positive = spent)
  const add = (obj, key, month, v) => { (obj[key] ??= {})[month] = ((obj[key][month] || 0) + v); };
  for (const t of txns) {
    balance[t.account] = (balance[t.account] || 0) + t.amount;
    const month = t.date.slice(0, 7);
    const acct = byId[t.account];
    if (!acct || acct.offbudget || t.transfer_id || !t.category || month < months[0]) continue;
    const c = catInfo[t.category];
    if (!c) continue;
    if (c.income) add(income, c.name, month, t.amount / 100);
    else add(spending, c.group, month, -t.amount / 100);
  }

  const snapshot = {
    updatedAt: new Date().toISOString(),
    months,                            // last entry is the current, partial month
    accounts: accounts.filter((a) => !a.closed).map((a) => ({
      name: a.name, type: accountType(a.name), offbudget: !!a.offbudget,
      balance: Math.round(balance[a.id] || 0) / 100,
    })),
    income, spending,
  };
  fs.writeFileSync(OUT + '.tmp', JSON.stringify(snapshot));
  fs.renameSync(OUT + '.tmp', OUT);
  console.log(`wrote ${snapshot.accounts.length} accounts, ${months[0]}..${months.at(-1)} to ${OUT}`);
})();
