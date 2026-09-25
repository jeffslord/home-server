// Exports Actual account balances by type to SQLite for the Grafana "Net worth"
// dashboard (monitor/grafana/generators/networth.py). Run by Ofelia after the
// investment sync; mounted into the actual-helpers image as actual-networth.
//
// Account type comes from the emoji the account name starts with, so a new
// account lands in the right bucket as long as it follows the naming scheme.
// History is rebuilt from every transaction on each run, so there is no state
// to keep: the output file can be deleted at any time.
const api = require('@actual-app/api');
const Database = require('better-sqlite3');
const { openBudget, closeBudget } = require('./utils');

const OUT = process.env.NETWORTH_DB || '/out/networth.sqlite';

const EMOJI_TYPES = [
  ['🏦', 'Cash'],
  ['💹', 'Investments'],
  ['👴', 'Retirement'],
  ['🏥', 'HSA'],
  ['🏠', 'Real estate'],
  ['🏚', 'Real estate'],   // mortgages net against the house: equity
  ['🚗', 'Vehicles'],
  ['💳', 'Credit cards'],
];
// Fallbacks for (closed) accounts that never got an emoji.
const NAME_TYPES = [
  [/\b(IRA|401K)\b/i, 'Retirement'],
  [/\bloan\b/i, 'Vehicles'],
];

function accountType(name) {
  for (const [emoji, type] of EMOJI_TYPES) if (name.startsWith(emoji)) return type;
  for (const [re, type] of NAME_TYPES) if (re.test(name)) return type;
  return 'Other';
}

// Noon UTC keeps the calendar date the same in every US browser timezone.
const toTime = (iso) => Date.parse(`${iso}T12:00:00Z`) / 1000;
const nextDay = (iso) => new Date(Date.parse(`${iso}T12:00:00Z`) + 86400e3).toISOString().slice(0, 10);

(async () => {
  await openBudget();

  const accounts = (await api.getAccounts()).map((a) => ({ ...a, type: accountType(a.name) }));
  const { data: txns } = await api.runQuery(
    api.q('transactions')
      .select(['account', 'date', 'amount'])
      .options({ splits: 'none' })    // parent amounts only; children sum to the same
  );
  await closeBudget();

  // Net change per account per day, in cents.
  const deltas = new Map(accounts.map((a) => [a.id, new Map()]));
  let first = null;
  for (const t of txns) {
    const d = deltas.get(t.account);
    if (!d) continue;
    d.set(t.date, (d.get(t.date) || 0) + t.amount);
    if (!first || t.date < first) first = t.date;
  }
  const today = new Date().toLocaleDateString('en-CA', { timeZone: process.env.TZ || 'America/New_York' });

  const db = new Database(OUT);
  db.exec(`
    CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, name TEXT, type TEXT,
      offbudget INTEGER, closed INTEGER, balance REAL);
    CREATE TABLE IF NOT EXISTS balances (time INTEGER, date TEXT, account_id TEXT,
      type TEXT, balance REAL, PRIMARY KEY (date, account_id));
    CREATE INDEX IF NOT EXISTS balances_time ON balances (time);
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
  `);
  const insAcct = db.prepare('INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)');
  const insBal = db.prepare('INSERT INTO balances VALUES (?, ?, ?, ?, ?)');
  const setMeta = db.prepare('INSERT OR REPLACE INTO meta VALUES (?, ?)');

  let rows = 0;
  db.transaction(() => {
    db.exec('DELETE FROM accounts; DELETE FROM balances;');
    for (const a of accounts) {
      const d = deltas.get(a.id);
      let bal = 0;
      let started = false;
      // One row per day from the account's first transaction on, so a per-type
      // SUM grouped by day is complete on every day (no gaps to interpolate).
      for (let day = first; first && day <= today; day = nextDay(day)) {
        if (d.has(day)) { bal += d.get(day); started = true; }
        if (started) { insBal.run(toTime(day), day, a.id, a.type, bal / 100); rows++; }
      }
      a.balance = bal / 100;
      insAcct.run(a.id, a.name, a.type, a.offbudget ? 1 : 0, a.closed ? 1 : 0, a.balance);
    }
    setMeta.run('updated_at', String(Math.floor(Date.now() / 1000)));
  })();
  db.close();

  const byType = {};
  for (const a of accounts) byType[a.type] = (byType[a.type] || 0) + a.balance;
  console.log(`wrote ${accounts.length} accounts, ${rows} daily balances (${first}..${today}) to ${OUT}`);
  console.log(Object.entries(byType).map(([k, v]) => `${k} ${Math.round(v)}`).join(', '));
})();
