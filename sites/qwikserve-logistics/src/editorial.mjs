import { joiningGuide, shortFilm } from "./journey.mjs";
import { company, riderStats, formatCount } from "./content.mjs";
import { button, callButton, cta, esc, eyebrow, icon, link, sectionTitle } from "./components.mjs";

export const rentalCopy = "EV rental is available only to riders working under Qwikserve. A separate rental company supplies the vehicles. Your coordinator can check local availability and explain the rental terms before handover.";

// [name, file key, artwork width, artwork height]. Wide wordmarks render
// shorter and compact marks taller, so every logo carries similar visual weight.
const logos = [
  ["Spencer’s", "spencers", 457, 107], ["Myntra", "myntra", 238, 250], ["DealShare", "dealshare", 233, 260],
  ["Zomato", "zomato", 260, 260, 38], ["Shadowfax", "shadowfax", 452, 143], ["Delhivery", "delhivery", 352, 104],
  ["Blue Dart", "blue-dart", 456, 86], ["Nykaa", "nykaa", 469, 158], ["Meadow", "meadow", 399, 260],
];
const logoHeight = (w, h, fixed) => fixed || Math.round(Math.min(48, 48 * Math.pow(w / h, -0.42)));

export const scenes = {
  dispatch: { src:"guide-ride-4.webp", width:1600, height:900, alt:"A rider in a jacket with the Qwikserve logo riding a motorbike with a delivery bag" },
  road: { src:"stock-rider.webp?v=2", width:1600, height:1050, alt:"A helmeted rider carrying parcels on a motorbike along a city road" },
  vehicle: { src:"stock-ev-charging.webp", width:1600, height:1067, alt:"An electric scooter plugged in at a street charging point" },
  recruiter: { src:"stock-recruiter.webp", width:1600, height:1067, alt:"A woman in office wear talking on a desk phone" },
};

export function scene(key, caption, priority=false) {
  const asset = scenes[key];
  return `<figure class="scene-frame" data-reveal>
    <img src="/assets/${asset.src}" srcset="/assets/${asset.src.replace('.webp','-small.webp')} 700w, /assets/${asset.src} ${asset.width}w" sizes="(max-width:700px) 94vw, 48vw" alt="${esc(asset.alt)}" width="${asset.width}" height="${asset.height}" ${priority?'fetchpriority="high"':'loading="lazy"'}>
    <figcaption><strong>${esc(caption)}</strong><span>Stock photo</span></figcaption>
  </figure>`;
}

export function rail(items, label, speed, extraControls=false) {
  const group = items.join("");
  return `<div class="moving-rail" data-rail data-speed="${speed}" aria-label="${esc(label)}">
    <div class="rail-window" tabindex="0" role="region" aria-label="${esc(label)}">
      <div class="rail-track"><ul class="rail-group">${group}</ul></div>
    </div>
    <div class="rail-controls" hidden>
      ${extraControls?'<button type="button" data-rail-prev aria-label="Previous rider">←</button>':""}
      <button type="button" data-rail-toggle aria-label="Pause scrolling">Pause</button>
      ${extraControls?'<button type="button" data-rail-next aria-label="Next rider">→</button>':""}
    </div>
  </div>`;
}

function partnerStrip() {
  const images = logos.map(([name, key, w, h, fixed])=>{const height=logoHeight(w,h,fixed);const width=Math.round(height*w/h);return `<li><img src="/assets/logo-${key}.webp" alt="${esc(name)}" width="${width}" height="${height}" style="height:${height}px;width:${width}px"></li>`;});
  return `<section class="partner-strip"><div class="container">
    <h2>Companies we’ve worked with</h2>
    ${rail(images,"Companies we’ve worked with",30)}
  </div></section>`;
}

const offerings = [
  ["people","Rider recruitment","Field sourcing, screening and onboarding around your reporting point.","/partners/#recruitment"],
  ["route","Ongoing manpower","Recruitment for regular shifts, new hubs and changing headcounts.","/partners/#ongoing"],
  ["parcel","Sector recruitment","Staffing for quick commerce, retail, courier and other delivery operations.","/partners/#industries"],
  ["scooter","Vehicles covered","Riders bring their own bike or ride a rented EV we arrange, so vehicles are not your concern.","/partners/#ev"],
];

export const roundDown=n=>Math.max(10,Math.floor(n/10)*10);

export function homePage() {
  return `${shortFilm("operations")}
  ${partnerStrip()}
  <section class="section container experience-ledger" aria-label="Company experience">
    <div>${eyebrow("QWIKSERVE IN NUMBERS")}<h2>Our work <br>on the ground.</h2>${link("Experience & highlights","/highlights/")}</div>
    <dl data-stat-api="${riderStats.api}"><div><dt data-stat="riders_total">${formatCount(riderStats.fallbackTotal)}</dt><dd>Riders onboarded with Qwikserve.</dd></div>
    <div><dt>2018</dt><dd>Founded in August, with our head office in Kolkata.</dd></div></dl>
    <p class="stat-note" data-stat-note>${riderStats.fallbackNote}</p>
  </section>
  <section class="section offers-section"><div class="container">
    <div class="section-heading"><div>${eyebrow("FOR PARTNER COMPANIES")}<h2>What does your<br><em>next shift need?</em></h2></div><p>From a new reporting point to an established hub, the starting point is your staffing requirement.</p></div>
    <div class="offer-grid">${offerings.map(([symbol,title,body,url])=>`<a href="${url}" class="offer-card" data-reveal><span class="offer-symbol">${icon(symbol)}</span><h3>${title}</h3><p>${body}</p><span class="offer-arrow">${icon("northeast")}</span></a>`).join("")}</div>
  </div></section>
  <section class="section container why-section" id="why-qwikserve">
    ${sectionTitle("WHY QWIKSERVE","One team from<br><em>first call to first shift.</em>","The right riders, on every shift. Here is what that means for your operation.")}
    <div class="team-grid">${[
      ["clock","Working since 2018","Recruiting and deploying delivery manpower from our Kolkata head office since August 2018."],
      ["route","End-to-end","Sourcing, screening, onboarding, deployment and support are handled by one team, not handed between agencies."],
      ["search","Field and phone reach","Field recruiters and telecallers reach riders in the neighbourhoods your hubs serve."],
      ["parcel","Many kinds of delivery","Experience across quick commerce, e-commerce, food, courier, retail, pharmacy and hyperlocal operations."],
      ["scooter","Riders without a vehicle","EV rental through a separate supplier, for riders working under Qwikserve, widens the pool you can draw from."],
      ["people","Support after deployment","Rider support and team leaders stay in touch once riders are at your hub."],
    ].map(([ic,h,b])=>`<article data-reveal>${icon(ic)}<h3>${h}</h3><p>${b}</p></article>`).join("")}</div>
  </section>
  <section class="section container field-notes"><div>${scene("recruiter","Recruitment desk")}</div><div>
    ${eyebrow("FROM THE FIELD")}<h2>Before a rider<br><em>reaches your hub.</em></h2>
    <p>A recruiter starts with the reporting point, the shift and the kind of delivery work involved. Those details shape the conversations with prospective riders and the briefing before they arrive.</p>
    ${link("See the four stages of recruitment","/partners/#process")}
  </div></section>
  ${evTeaser()}
  ${joiningGuide(true)}${cta("Where do you need riders?","Share your reporting location, shift timings and approximate headcount.")}`;
}

export function directContact() {
  return `<div class="direct-contact"><span>Prefer to talk?</span>${callButton("Call the team")}<a href="${company.whatsapp.href}" target="_blank" rel="noopener">${company.whatsapp.label} ${icon("northeast")}</a><a href="mailto:${company.email}">${company.email}</a></div>`;
}


// The upcoming Qwikserve EV brand. Name, specs and launch date are not public
// yet, so the copy stays at "coming soon". Partner and Join pages link here.
export function evTeaser() {
  return `<section class="ev-teaser" id="ev-brand" aria-labelledby="ev-brand-title"><div class="container">
    <div class="ev-teaser-card" data-reveal>
      <div class="ev-teaser-glow" aria-hidden="true"></div>
      <div class="ev-teaser-copy">
        <span class="ev-badge"><i aria-hidden="true"></i>Coming soon</span>
        <h2 id="ev-brand-title">Our own EV brand<br><em>is on its way.</em></h2>
        <p>After years of putting riders on rented electric scooters, we’re building our own: electric two-wheelers designed around the delivery shift, backed by the same team that supports our riders every day.</p>
        <ul class="ev-points">
          <li>${icon("bolt")}<span>Built for full delivery shifts</span></li>
          <li>${icon("scooter")}<span>For Qwikserve riders first</span></li>
          <li>${icon("people")}<span>Serviced by people who know riders</span></li>
        </ul>
        <div class="ev-actions">${link("EVs for partners","/partners/#ev")}${link("EVs for riders","/join/#ev-options")}</div>
      </div>
      <div class="ev-teaser-visual" aria-hidden="true">
        <div class="ev-orb"><span class="ev-orbit o1"></span><span class="ev-orbit o2"></span><span class="ev-orbit o3"></span>
          <span class="ev-core"><svg viewBox="0 0 24 24"><path d="m14 2-11 13h8l-1 7L21 9h-8z"/></svg></span>
          <span class="ev-charge"><b></b></span></div>
      </div>
    </div>
  </div></section>`;
}

// Rider-journey slideshows (Partners page). Each slide names its final photo;
// until that file is in src/assets, a current stock photo stands in.
import { existsSync as fileExists } from "node:fs";
const journeyPhotos = {
  "journey-call":   {fallback:"stock-recruiter.webp", alt:"A recruiter on a phone call at an office desk"},
  "journey-forms":  {fallback:"guide-ride-2.webp", alt:"A new rider filling in onboarding paperwork"},
  "journey-hub":    {fallback:"stock-warehouse.webp", alt:"Delivery staff together inside a stocked warehouse hub"},
  "journey-road":   {fallback:"guide-ride-4.webp", alt:"A helmeted rider on a scooter in Indian city traffic"},
  "journey-door":   {fallback:"guide-ride-3.webp", alt:"A parcel handed over a gate to a customer"},
  "journey-brief":  {fallback:"stock-recruiter.webp", alt:"Two colleagues discussing a staffing plan in an office"},
  "journey-source": {fallback:"guide-ride-1.webp", alt:"Riders on scooters in a busy Indian street"},
  "journey-ready":  {fallback:"stock-warehouse.webp", alt:"Workers moving a parcel through warehouse aisles"},
  "journey-rain":   {fallback:"guide-ride-4.webp", alt:"A rider on a scooter riding through the rain"},
  "journey-cover":  {fallback:"guide-ride-2.webp", alt:"A rider in a blue helmet checking his phone at the handlebars"},
};
function journeyPhoto(key) {
  const own = fileExists(new URL("./assets/" + key + ".webp", import.meta.url));
  const file = own ? key + ".webp" : journeyPhotos[key].fallback;
  const small = file.replace(".webp", "-small.webp");
  const hasSmall = fileExists(new URL("./assets/" + small, import.meta.url));
  return { src:"/assets/" + file, srcset: hasSmall ? `/assets/${small} 700w, /assets/${file} 1600w` : "", alt: journeyPhotos[key].alt };
}
export const journeys = {
  rider: [
    ["journey-call","Day 1","The first call","A recruiter talks through the area, the shift and the vehicle."],
    ["journey-forms","Day 2","Paperwork, done right","Documents checked and onboarding completed before day one."],
    ["journey-hub","Day 3","Briefed at the hub","The rider meets the team leader and learns the reporting point."],
    ["journey-road","Day 4","The first shift","Out on your routes, on their own bike or a rental EV."],
    ["journey-door","Every day after","At the doorstep","Support stays one call away, for the rider and for your hub."],
  ],
  brief: [
    ["journey-brief","Step 1","Your brief","Reporting point, shift pattern and headcount, in one conversation."],
    ["journey-source","Step 2","Sourced near your hub","Field recruiters find riders who live close enough to report on time."],
    ["journey-ready","Step 3","Ready at the reporting point","Screened, onboarded and briefed before the first shift."],
    ["journey-rain","Step 4","On the route, rain or shine","Team leaders stay with riders through the working day."],
    ["journey-cover","Step 5","Every shift covered","Replacements arranged when someone drops off, without you chasing."],
  ],
};
export function slideshow(name, label, priority=false) {
  const slides = journeys[name];
  return `<figure class="journey-show" data-slideshow aria-roledescription="carousel" aria-label="${esc(label)}" data-reveal>
    <div class="journey-slides">${slides.map(([key,kicker,title],i)=>{const p=journeyPhoto(key);return `<div class="journey-slide${i?"":" is-active"}" role="group" aria-roledescription="slide" aria-label="${i+1} of ${slides.length}: ${esc(title)}" ${i?'aria-hidden="true"':""}>
      <img src="${p.src}" ${p.srcset?`srcset="${p.srcset}" sizes="(max-width:700px) 94vw, 48vw"`:""} width="1600" height="1067" alt="${esc(p.alt)}" ${i===0&&priority?'fetchpriority="high"':'loading="lazy"'} decoding="async"></div>`;}).join("")}</div>
    <div class="journey-progress-bar" aria-hidden="true">${slides.map(()=>"<i><b></b></i>").join("")}</div>
    <figcaption class="journey-caption">
      <div class="journey-captions">${slides.map(([,kicker,title,body],i)=>`<div class="journey-cap${i?"":" is-active"}" ${i?'aria-hidden="true"':""}><span>${esc(kicker)}</span><strong>${esc(title)}</strong><p>${esc(body)}</p></div>`).join("")}</div>
      <div class="journey-controls"><button type="button" data-show-prev aria-label="Previous slide">${icon("arrow","flip")}</button><button type="button" data-show-toggle aria-label="Pause slideshow"><span class="playback-glyph" aria-hidden="true"></span></button><button type="button" data-show-next aria-label="Next slide">${icon("arrow")}</button></div>
    </figcaption>
    <span class="journey-credit">Stock photos</span>
  </figure>`;
}
