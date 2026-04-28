const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
  const browser = await puppeteer.launch({
    headless: "new",
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      '--window-size=1280,720'
    ]
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  
  console.log("Navigating to localhost:3000...");
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  console.log("Waiting for loading overlay to disappear...");
  try {
    await page.waitForFunction(() => {
      const el = document.getElementById('loading-overlay');
      return !el || el.style.display === 'none';
    }, { timeout: 15000 });
  } catch (e) {
    console.log("Loading overlay didn't disappear, trying to force hide it.");
    await page.evaluate(() => {
      const el = document.getElementById('loading-overlay');
      if (el) el.style.display = 'none';
    });
  }

  // Type "안녕" and click send
  console.log("Typing '안녕'...");
  await page.type('#chat-input', '안녕');
  await page.click('#btn-send');
  
  console.log("Waiting 1.5 seconds for animation to play...");
  await new Promise(r => setTimeout(r, 1500));
  
  console.log("Taking screenshot...");
  await page.screenshot({ path: 'avatar_test.png' });
  
  await browser.close();
  console.log("Done.");
})();
