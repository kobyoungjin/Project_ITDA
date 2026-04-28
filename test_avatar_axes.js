const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({
    headless: "new",
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--window-size=1280,720']
  });
  
  // Test 1: Original (no flip)
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  try {
    await page.waitForFunction(() => {
      const el = document.getElementById('loading-overlay');
      return !el || el.style.display === 'none';
    }, { timeout: 15000 });
  } catch (e) {}

  await page.type('#chat-input', '안녕');
  await page.click('#btn-send');
  await new Promise(r => setTimeout(r, 600)); // Wait 600ms (mid-animation)
  await page.screenshot({ path: 'test_original.png' });
  
  // Test 2: X-axis 180
  await page.evaluate(() => {
    window.TEST_FLIP_AXIS = 'X';
  });
  await page.click('#btn-send');
  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: 'test_x.png' });

  // Test 3: Y-axis 180
  await page.evaluate(() => {
    window.TEST_FLIP_AXIS = 'Y';
  });
  await page.click('#btn-send');
  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: 'test_y.png' });

  // Test 4: Z-axis 180
  await page.evaluate(() => {
    window.TEST_FLIP_AXIS = 'Z';
  });
  await page.click('#btn-send');
  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: 'test_z.png' });

  await browser.close();
  console.log("Screenshots captured.");
})();
