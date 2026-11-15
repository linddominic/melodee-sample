// SPDX-License-Identifier: AGPL-3.0-only
// Melodee Listen: in the window the Kits page opens for Listen (its name "splice-listen", or "#melodee-listen" on the
// link), trims a Splice sound's page to its name, waveform and Play button, and presses Play: Splice's own page and
// player, in one's own browser. Any other splice.com tab is left as it is. Nothing is read from the page or sent.
(() => {
  if (window.name !== "splice-listen" && location.hash !== "#melodee-listen") return;
  if (window.__melodeeListen) return;
  window.__melodeeListen = true;

  const style = document.createElement("style");
  style.textContent = `
    html, body { background: #17141F !important; overflow: hidden !important; }
    body * { visibility: hidden !important; }
    .melodee-show, .melodee-show * { visibility: visible !important; }
    .melodee-wave { position: fixed !important; left: 14px !important; right: 14px !important; top: 44px !important; width: auto !important;
                    height: 120px !important; margin: 0 !important; z-index: 2147483646 !important; }
    .melodee-wave canvas { width: 100% !important; height: 100% !important; }
    .melodee-play { position: fixed !important; left: 14px !important; top: 178px !important; margin: 0 !important; z-index: 2147483647 !important; }
    #melodee-title { position: fixed; left: 14px; right: 14px; top: 12px; z-index: 2147483647; visibility: visible !important;
                     font: 600 14px -apple-system, system-ui, sans-serif; color: #eee; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }`;
  document.documentElement.append(style);
  const title = document.createElement("div");
  title.id = "melodee-title";
  title.textContent = document.title.replace(/ \| Splice.*$/, "");
  document.body.append(title);

  let tries = 0;
  const look = setInterval(() => {
    const play = document.querySelector('[data-qa="play-button"]'), wave = document.querySelector('[data-qa="sounds.waveform-preview"]');
    if (play && wave) {
      clearInterval(look);
      play.classList.add("melodee-show", "melodee-play");
      wave.classList.add("melodee-show", "melodee-wave");
      if (play.getAttribute("data-play") === "true") play.click(); // Splice's own Play; the browser may ask for a press first
    } else if (++tries > 150) { // the page changed: shown whole rather than empty
      clearInterval(look);
      style.remove();
      title.remove();
    }
  }, 100);
})();
