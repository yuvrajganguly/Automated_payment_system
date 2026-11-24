import { button, esc, icon, link } from "./components.mjs";
import { media } from "./content.mjs";
import { riderInterviews } from "./rider-interviews.mjs";
import { existsSync } from "node:fs";

export function shortFilm(slot) {
  const film = media[slot];
  const home = slot === "operations";
  const headline = home ? "Delivery riders<br>for your operation." : "Your next<br>delivery shift.";
  const introduction = home ? "Recruitment, onboarding and rider support for your delivery hubs." : "Find a local assignment and get ready for your first shift.";
  const primary = home ? button("Discuss your requirement", "/partners/#enquire") : button("Enquire about joining", "#apply");
  const secondary = home ? link("Join as a rider", "/join/") : link("How to join", "#how-to-join");
  const watch = film.video ? `<button class="feature-watch" type="button" data-video="${esc(film.video)}" data-captions="${esc(film.captions)}" data-transcript="${esc(film.transcript)}">Watch the full film</button>` : "";
  return `<section class="field-hero" aria-labelledby="film-headline">
    <figure class="short-film">
      <img class="film-cover" src="${esc(film.poster)}" width="1280" height="720" fetchpriority="high" alt="${esc(film.description)}">
      <video data-loop-src="${esc(film.loop)}" poster="${esc(film.poster)}" muted loop playsinline preload="none" aria-hidden="true"></video>
      <figcaption><span class="film-caption">Illustrative footage</span>${watch}
        <button class="pause-film" type="button" hidden aria-label="Pause film"><span class="playback-glyph" aria-hidden="true"></span></button>
      </figcaption>
    </figure>
    <div class="film-intro"><h1 id="film-headline">${headline}</h1><p>${introduction}</p>
      <div class="film-actions">${primary}${secondary}</div>
    </div>
  </section>`;
}

const steps = [
  ["Tell us where you ride", "Give the recruiter your preferred area, when you can work and whether you have your own vehicle.", "guide-ride-1.webp", "A rider with the Qwikserve logo on his helmet and jacket, carrying parcels on a scooter"],
  ["Talk through the shift", "Ask about the hub, shift timings and delivery work. Your recruiter will explain which local assignments are available.", "guide-ride-2.webp", "A rider in a Qwikserve helmet checking the route on a phone mounted to his scooter"],
  ["Get ready for onboarding", "Check the documents you need. If you plan to rent an EV, discuss the supplier’s terms and local availability with your coordinator.", "guide-ride-3.webp", "A rider in a Qwikserve helmet adjusting his goggles before setting off"],
  ["Meet the team at the hub", "Confirm the time, address and person to ask for. Keep the coordinator’s number handy for your first visit.", "guide-ride-4.webp", "A rider in a Qwikserve jacket heading out on a motorbike with a delivery bag"]
];

export function joiningGuide(home = false) {
  const action = home ? button("Explore rider opportunities", "/join/") : button("Enquire about joining", "#apply");
  const stepsHtml = steps.map(([title, body], index) => `<li id="join-stage-${index+1}">
    <button type="button" data-stage="${index}" aria-controls="guide-image-${index}" aria-pressed="${index===0}">
      <span>${String(index+1).padStart(2,"0")}</span>${esc(title)}</button><p>${esc(body)}</p>
  </li>`).join("");
  const pictures = steps.map(([title, , file, alt], index) => `<figure class="guide-image ${index===0?"active":""}" id="guide-image-${index}" aria-hidden="${index!==0}">
    <img src="/assets/${file}" srcset="/assets/${file.replace(".webp", "-small.webp")} 700w, /assets/${file} ${[1600,1600,1280,1600][index]}w" sizes="(max-width:700px) 93vw, 49vw" width="1000" height="750" loading="lazy" alt="Stock photo of ${esc(alt.charAt(0).toLowerCase()+alt.slice(1))}">
    <figcaption><b>${esc(title)}</b><small>Stock photo</small></figcaption></figure>`).join("");
  return `<section class="joining-guide journey-section" id="how-to-join" data-guide>
    <div class="container">
      <div class="journey-title"><h2>How to join <em>Qwikserve.</em></h2>${home?link(riderInterviews.some(r=>r.quote)?"What our riders say":"Meet our riders","/join/#rider-stories"):""}</div>
      <div class="guide-layout"><div class="guide-itinerary"><ol class="guide-list">${stepsHtml}</ol>${action}</div>
        <div class="guide-view"><div class="guide-pictures">${pictures}</div>
          <div class="guide-navigation" hidden><span role="status" data-guide-position>Step 1 of 4</span>
            <div class="journey-progress" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
            <div><button type="button" data-guide-prev aria-label="Previous joining step">←</button><button type="button" data-guide-next aria-label="Next joining step">→</button></div>
          </div>
        </div>
      </div>
    </div>
  </section>`;
}

function portraitFile(name) { return name.toLowerCase().replaceAll(" ", "-") + ".webp"; }
function hasPortrait(name) { return existsSync(new URL("./assets/rider-portraits/" + portraitFile(name), import.meta.url)); }

function portrait(name) {
  const file = name.toLowerCase().replaceAll(" ", "-") + ".webp";
  const words = name.split(" ");
  const initials = words[0][0] + words.at(-1)[0];
  if (existsSync(new URL("./assets/rider-portraits/" + file, import.meta.url))) {
    return `<img loading="lazy" decoding="async" class="rider-avatar" src="/assets/rider-portraits/${file}" data-initials="${esc(initials)}" width="300" height="360" alt="">`;
  }
  return `<span class="rider-avatar" aria-hidden="true">${esc(initials)}</span>`;
}

export function riderStories(rail) {
  // Only words a rider has approved (quote) are published. Suggested lines
  // (draft) stay in the source for the confirmation round and never render.
  // Riders with a photo appear in the moving rail; a quote shows on the card once it is filled in.
  const quoted = riderInterviews.filter(rider => rider.quote);
  const shown = quoted.length ? quoted : riderInterviews.filter(rider => hasPortrait(rider.name));
  const anyQuote = shown.some(rider => rider.quote);
  const cards = shown.map(({name, quote, recognition}) => quote ? `<li class="rider-card review-card">
    <header class="review-person">${portrait(name)}<div><strong>${esc(name)}</strong>${recognition ? `<span class="review-recognition">${esc(recognition)}</span>` : ""}<small>Qwikserve rider</small></div></header>
    <blockquote>“${esc(quote)}”</blockquote>
  </li>` : `<li class="rider-card review-card portrait-card">${portrait(name)}<div><strong>${esc(name)}</strong><small>Qwikserve rider</small></div></li>`);
  return `<section id="rider-stories" class="section riders-section"><div class="container">
    <div class="stories-heading"><h2>${anyQuote ? "What our <em>riders say</em>" : "Meet our <em>riders</em>"}</h2>${anyQuote ? "" : "<p>A few of the people riding with Qwikserve today.</p>"}</div>
    ${rail(cards, anyQuote ? "Rider reviews" : "Qwikserve riders", 14, true)}
  </div></section>`;
}
