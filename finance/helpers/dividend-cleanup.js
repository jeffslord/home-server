// Money-market dividends in the Vanguard Cash Plus and Fidelity Cash accounts
// arrive from bank sync as a +dividend / -reinvestment pair on the same day.
// The reinvested shares stay in the same account, so the - leg is not real:
// keeping it makes Actual's balance drift below the bank's and hides the
// dividend income. This deletes the - leg and files the + leg under
// Interest & Dividends. Run daily by Ofelia; DRY_RUN=1 only prints.
//
// Deleted legs stay deleted because the accounts' "reimport deleted
// transactions" bank-sync setting was switched off (2026-10-21).
const api = require('@actual-app/api');
const { openBudget, closeBudget } = require('./utils');

const DRY = process.env.DRY_RUN === '1';
const CATEGORY = '🏦 Interest & Dividends';
// account name -> [dividend leg notes, reinvestment leg notes]
const ACCOUNTS = {
  '🏦 Vanguard - Cash Plus': [/^VANGUARD CASH PLUS$/, /^VANGUARD CASH PLUS$/],
  '🏦 Fidelity - Cash': [/^DIVIDEND RECEIVED/, /^REINVESTMENT/],
};

(async () => {
  await openBudget();
  const category = (await api.getCategories()).find((c) => c.name === CATEGORY);
  if (!category) throw new Error(`category not found: ${CATEGORY}`);
  const accounts = await api.getAccounts();
  let changes = 0;

  for (const [name, [divRe, reinvRe]] of Object.entries(ACCOUNTS)) {
    const acct = accounts.find((a) => a.name === name);
    if (!acct) { console.log(`account not found, skipping: ${name}`); continue; }
    const { data: txns } = await api.runQuery(api.q('transactions')
      .filter({ account: acct.id }).select(['id', 'date', 'amount', 'notes', 'category']));

    for (const plus of txns.filter((t) => t.amount > 0 && divRe.test(t.notes || ''))) {
      const minus = txns.find((t) => t.date === plus.date && t.amount === -plus.amount && reinvRe.test(t.notes || ''));
      if (!minus) continue;   // a lone dividend is already fine
      console.log(`${name} ${plus.date} ${(plus.amount / 100).toFixed(2)}: delete reinvestment leg, dividend -> ${CATEGORY}`);
      changes++;
      if (DRY) continue;
      await api.deleteTransaction(minus.id);
      if (plus.category !== category.id) await api.updateTransaction(plus.id, { category: category.id });
    }
  }
  console.log(`${changes} dividend pair(s) ${DRY ? 'found (dry run)' : 'fixed'}`);
  await closeBudget();
})().catch((e) => { console.error(e); process.exit(1); });
