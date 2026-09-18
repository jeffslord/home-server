const api = require('@actual-app/api');
const { closeBudget, ensurePayee, getAccountBalance, getAccountNote, getTagValue, openBudget, showPercent } = require('./utils');
require("dotenv").config();

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'application/json',
};

function parseRedfin(text) {
  return JSON.parse(text.replace(/^\{\}&&/, ''));
}

async function getPropertyId(address) {
  const encoded = encodeURIComponent(address.replace(/%20/g, ' ').replace(/%2C/g, ','));
  const url = `https://www.redfin.com/stingray/do/location-autocomplete?location=${encoded}&v=2`;
  const res = await fetch(url, { headers: HEADERS });
  const data = parseRedfin(await res.text());
  const rows = data?.payload?.sections?.[0]?.rows;
  if (!rows?.length) throw new Error(`No Redfin results for address: ${address}`);
  const propertyId = rows[0]?.id?.propertyId;
  if (!propertyId) throw new Error(`No propertyId found for address: ${address}`);
  return propertyId;
}

async function getRedfinEstimate(propertyId) {
  const url = `https://www.redfin.com/stingray/api/home/details/avm?propertyId=${propertyId}&accessLevel=3`;
  const res = await fetch(url, { headers: HEADERS });
  const data = parseRedfin(await res.text());
  const value = data?.payload?.predictedValue;
  if (!value) throw new Error(`No estimate returned for propertyId: ${propertyId}`);
  return value * 100; // convert to cents
}

(async function () {
  await openBudget();

  const payeeId = await ensurePayee(process.env.REDFIN_PAYEE_NAME || 'Redfin Estimate');

  const accounts = await api.getAccounts();
  for (const account of accounts) {
    const note = await getAccountNote(account);
    if (!note) continue;

    const address = getTagValue(note, 'address');
    if (!address) continue;

    const ownership = note.indexOf('ownership:') > -1
      ? parseFloat(getTagValue(note, 'ownership'))
      : 1;

    console.log('Fetching Redfin estimate for account:', account.name);

    try {
      const propertyId = await getPropertyId(address);
      console.log('Property ID:', propertyId);
      const value = await getRedfinEstimate(propertyId);
      const balance = await getAccountBalance(account);
      const diff = Math.round(value * ownership) - balance;

      console.log('Redfin Value:', value / 100);
      console.log('Ownership:', showPercent(ownership));
      console.log('Balance:', balance / 100);
      console.log('Difference:', diff / 100);

      if (diff !== 0) {
        await api.importTransactions(account.id, [{
          date: new Date(),
          payee: payeeId,
          amount: diff,
          cleared: true,
          reconciled: true,
          notes: `Update value to ${Math.round(value * ownership) / 100} (${value / 100} * ${showPercent(ownership)})`,
        }]);
        console.log('Transaction added.');
      } else {
        console.log('No change, skipping.');
      }
    } catch (e) {
      console.error('Error updating account:', account.name, e.message);
    }
  }

  await closeBudget();
})();
