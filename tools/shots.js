const { chromium } = require('playwright-core');
const path = require('path');

const BASE = 'http://127.0.0.1:5001';
const OUT = path.join(__dirname, 'shots');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });

  async function shot(name) {
    await page.screenshot({ path: path.join(OUT, name), fullPage: true });
    console.log('截图', name);
  }
  async function login(u) {
    await page.goto(BASE + '/login', { waitUntil: 'networkidle' });
    await page.fill('[name=username]', u);
    await page.fill('[name=password]', 'meddemo');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.click('form button.btn'),
    ]);
  }

  // 公共首页（未登录）
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await shot('01_公共首页.png');

  // 中选详情（公开）
  await page.goto(BASE + '/selected/16', { waitUntil: 'networkidle' });
  await shot('06_中选详情.png');

  // 医院工作台
  await login('hospital01');
  await shot('02_医院采购工作台.png');
  // 核验中心（登录可见）
  await page.goto(BASE + '/verify', { waitUntil: 'networkidle' });
  await shot('07_核验中心.png');

  // 药企工作台
  await page.goto(BASE + '/logout', { waitUntil: 'networkidle' });
  await login('pharma01');
  await shot('03_药企合规工作台.png');

  // 研究员工作台
  await page.goto(BASE + '/logout', { waitUntil: 'networkidle' });
  await login('researcher01');
  await shot('04_研究员工作台.png');

  // 管理员工作台
  await page.goto(BASE + '/logout', { waitUntil: 'networkidle' });
  await login('admin');
  await shot('05_管理员工作台.png');

  await browser.close();
  console.log('全部完成');
})().catch(e => { console.error('ERROR', e.message); process.exit(1); });
