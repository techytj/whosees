// Screenshot the website like a visitor scrolling: one viewport at a time.
// Usage: electron tools/site-shot.js <html file> <width> <height> <out-prefix>
const { app, BrowserWindow } = require('electron');
const [file, width, height, out] = process.argv.slice(-4);
app.whenReady().then(async () => {
  const w = new BrowserWindow({ show: false, width: +width, height: +height, useContentSize: true, webPreferences: { offscreen: true } });
  await w.loadFile(file);
  await new Promise((r) => setTimeout(r, 6500)); // let the hero animation play
  const total = await w.webContents.executeJavaScript('document.documentElement.scrollHeight');
  let i = 0;
  for (let y = 0; y < total; y += +height) {
    await w.webContents.executeJavaScript(`window.scrollTo(0, ${y}); document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'));`);
    await new Promise((r) => setTimeout(r, 900));
    const img = await w.webContents.capturePage();
    require('fs').writeFileSync(`${out}-${String(i++).padStart(2, '0')}.png`, img.toPNG());
  }
  console.log('pages', i, 'height', total);
  app.quit();
});
