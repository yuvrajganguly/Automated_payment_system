import { joiningGuide, shortFilm } from "./journey.mjs";
import { company, riderStats, formatCount } from "./content.mjs";
import { button, callButton, cta, esc, eyebrow, icon, link, sectionTitle } from "./components.mjs";

export const rentalCopy = "EV rental is available only to riders working under Qwikserve. A separate rental company supplies the vehicles. Your coordinator can check local availability and explain the rental terms before handover.";

// [name, file key, artwork width, artwork height]. Wide wordmarks render
// shorter and compact marks taller, so every logo carries similar visual weight.
const logos = [
  ["Spencer’s", "spencers", 457, 107], ["Myntra", "myntra", 238, 250], ["DealShare", "dealshare", 233, 260],
  ["Zomato", "zomato", 472, 100], ["Shadowfax", "shadowfax", 452, 143], ["Delhivery", "delhivery", 352, 104],
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
    <div><dt>2019</dt><dd>Founded in August, with our head office in Kolkata.</dd></div></dl>
    <p class="stat-note" data-stat-note>${riderStats.fallbackNote}</p>
  </section>
  <section class="section offers-section"><div class="container">
    <div class="section-heading"><div>${eyebrow("FOR PARTNER COMPANIES")}<h2>What does your<br><em>next shift need?</em></h2></div><p>From a new reporting point to an established hub, the starting point is your staffing requirement.</p></div>
    <div class="offer-grid">${offerings.map(([symbol,title,body,url])=>`<a href="${url}" class="offer-card" data-reveal><span class="offer-symbol">${icon(symbol)}</span><h3>${title}</h3><p>${body}</p><span class="offer-arrow">${icon("northeast")}</span></a>`).join("")}</div>
  </div></section>
  <section class="section container why-section" id="why-qwikserve">
    ${sectionTitle("WHY QWIKSERVE","One team from<br><em>first call to first shift.</em>","The right riders, on every shift. Here is what that means for your operation.")}
    <div class="team-grid">${[
      ["clock","Working since 2019","Recruiting and deploying delivery manpower from our Kolkata head office since August 2019."],
      ["route","End-to-end","Sourcing, screening, onboarding, deployment and support are handled by one team, not handed between agencies."],
      ["search","Field and phone reach","Field recruiters and telecallers reach riders in the neighbourhoods your hubs serve."],
      ["parcel","Many kinds of delivery","Experience across quick commerce, e-commerce, food, courier, retail, pharmacy and hyperlocal operations."],
      ["scooter","Riders without a vehicle","EV rental through a separate supplier, for riders working under Qwikserve, widens the pool you can draw from."],
      ["people","Support after deployment","Rider support and team leaders stay in touch once riders are at your hub."],
    ].map(([ic,h,b])=>`<article data-reveal>${icon(ic)}<h3>${h}</h3><p>${b}</p></article>`).join("")}</div>
  </section>
  <section class="section container field-notes"><div>${slideshow("prep","Before a rider reaches your hub")}</div><div>
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

// Field slideshows. Documentary street photos from Indian cities (Pexels,
// free licence). Files are src/assets/field-<pexels id>.webp; a slide whose
// file is missing falls back to an existing photo so the build never breaks.
import { existsSync as fileExists } from "node:fs";
const fieldPhotos = {
  35803222:["Two delivery riders with delivery bags riding through the city at night","On the road"],
  7363190:["A delivery rider with an orange delivery box on his scooter","On the road"],
  7363125:["A uniformed delivery rider on his scooter with a delivery box","Ready to ride"],
  13311393:["A delivery rider with a Qwikserve delivery bag on his motorbike","On the road"],
  31332062:["A delivery rider in a red helmet with a delivery backpack on his motorbike","On the road"],
  11206901:["A delivery rider with a delivery box riding out on his scooter","On the road"],
  25048304:["A Qwikserve delivery rider riding through a flooded Kolkata street","Kolkata"],
  37059837:["A courier in a red helmet carrying parcels on a motorbike","On the road"],
  33359127:["A Qwikserve delivery rider with a loaded bag on his motorbike","Kolkata"],
  39978119:["A food delivery rider on a scooter with an insulated bag","On the road"],
  6682787:["A delivery rider in red handing a parcel to a smiling customer at his door","Doorstep"],
  13062478:["A telecaller with a headset on a call at her desk","Recruitment desk"],
  7362949:["A uniformed delivery rider on his motorbike checking the next drop on his phone","On the road"],
  33136687:["A rider on a scooter riding through monsoon rain","India"],
  11091214:["A Qwikserve rider in a red T-shirt beside parked motorbikes at a Kolkata street hub","Kolkata"],
  28928633:["A rider on a scooter in a busy market street","Punjab"],
  12203733:["A rider on his scooter checking a message on his phone","India"],
  4487383:["Two workers carrying a parcel down a stocked hub aisle","Hub"],
  24976284:["A helmeted rider on a scooter heading out on a city road","India"],
  6994107:["A parcel handed over a gate to a smiling customer","Doorstep"],
  39948199:["A rider carrying stacked parcels on a motorbike","On the road"],
  7580860:["A recruiter on a call at his desk","Recruitment desk"],
  33628086:["A rider in a yellow raincoat on a flooded street in West Bengal","West Bengal"],
  25810543:["A courier riding through the city at night with a loaded delivery bag","Bengaluru"],
  29469905:["A rider on a motorcycle in a crowded market lane","Varanasi"],
  28624791:["A rider balancing a heavy load of goods on a motorcycle in city traffic","India"],
  38107476:["Workers unloading goods from a truck","Kolkata"],
  39351202:["Workers sorting cardboard boxes across a warehouse floor","India"],
  13369323:["Customers at a neighbourhood shop with motorcycles parked outside","India"],
  27786496:["A young man smiling at a call on his phone in a busy market","Mumbai"],
  14335349:["A man on a parked motorcycle checking his phone outside a shop","Mumbai"],
  12333458:["A motorcyclist carrying goods through highway traffic","Karnataka"],
  36569208:["A delivery tricycle stacked with parcels on a misty street","India"],
  13652096:["A cycle rickshaw loaded with boxes in a sunlit alley","India"],
  38107477:["A man steadying a loaded bicycle on a busy street","Kolkata"],
  21923095:["A rider carrying large sacks on a motorbike","Bengaluru"],
  19673703:["A newspaper delivery on a bicycle on a misty morning","Kolkata"],
  33224085:["A dabbawala cycling through the streets with lunch deliveries","Mumbai"],
};
const fallbacks = ["guide-ride-1.webp","guide-ride-2.webp","guide-ride-3.webp","guide-ride-4.webp"];
function fieldPhoto(id, i) {
  const file = "field-" + id + ".webp";
  const own = fileExists(new URL("./assets/" + file, import.meta.url));
  const use = own ? file : fallbacks[i % fallbacks.length];
  const small = use.replace(".webp", "-small.webp");
  const hasSmall = fileExists(new URL("./assets/" + small, import.meta.url));
  return { src:"/assets/" + use, srcset: hasSmall ? `/assets/${small} 700w, /assets/${use} 1600w` : "", alt: fieldPhotos[id][0], place: fieldPhotos[id][1] };
}
// [pexels id, short title, one factual line]
export const journeys = {
  rider: [
    [33628086,"Rain or shine","Riders who turn up for the shift, whatever the weather."],
    [39948199,"Parcels","Briefed on the load before the first run."],
    [35803222,"Late shifts","Night slots and late dispatches staffed like any other."],
    [7363190,"Every drop","Parcels and orders taken door to door across your zone."],
  ],
  brief: [
    [13062478,"Your brief","A recruiter takes your reporting point, shifts and headcount."],
    [11091214,"Your hub","Riders reporting at your hub, ready for the shift."],
    [39351202,"Your shifts","Sorting and dispatch windows set how many riders you need."],
    [7362949,"Your routes","Riders who know the streets your hub serves."],
  ],
  join: [
    [12203733,"Contact us","Call, WhatsApp or send the form. A recruiter calls you back about your area and vehicle."],
    [4487383,"Go to the hub","Meet the team at your hub, finish onboarding and learn the shift."],
    [24976284,"Start riding","Ride your own bike or a rental EV on routes near home."],
    [6682787,"Deliver","Hand the order over at the door. Support stays a call away."],
  ],
  prep: [
    [7363125,"Found nearby","Field recruiters and telecallers reach riders where they live."],
    [13311393,"Vehicle sorted","Own bike, or a rental EV for riders working with us."],
    [31332062,"Briefed","Shift times, the reporting point and the kind of load."],
    [11206901,"Ready","Riders arrive knowing who to ask for at the hub."],
  ],
  lastmile: [
    [25048304,"Kolkata first","Our home ground since 2019, monsoon included."],
    [37059837,"Any load","Parcels, groceries and bulk retail drops."],
    [33359127,"Any lane","Riders who know the neighbourhood reach doors faster."],
    [39978119,"The last mile","Getting it to the door is the job that matters."],
  ],
};
export function slidePhotos(name, lazy=false) {
  const slides = journeys[name];
  return `<div class="field-frame">${slides.map(([id,title],i)=>{const p=fieldPhoto(id,i);return `<div class="field-slide${i?"":" is-active"}" role="group" aria-roledescription="slide" aria-label="${i+1} of ${slides.length}: ${esc(title)}" ${i?'aria-hidden="true"':""}>
      <img src="${p.src}" ${p.srcset?`srcset="${p.srcset}" sizes="(max-width:700px) 94vw, 52vw"`:""} width="1600" height="1067" alt="${esc(p.alt)}" loading="lazy" decoding="async">
      <span class="field-tag">${esc(p.place)} · Stock photo</span></div>`;}).join("")}</div>`;
}
export function slideshow(name, label, priority=false) {
  const slides = journeys[name];
  const pics = slides.map(([id],i)=>fieldPhoto(id,i));
  return `<figure class="field-show" data-slideshow aria-roledescription="carousel" aria-label="${esc(label)}" data-reveal>
    <div class="field-frame">${slides.map(([id,title],i)=>{const p=pics[i];return `<div class="field-slide${i?"":" is-active"}" role="group" aria-roledescription="slide" aria-label="${i+1} of ${slides.length}: ${esc(title)}" ${i?'aria-hidden="true"':""}>
      <img src="${p.src}" ${p.srcset?`srcset="${p.srcset}" sizes="(max-width:700px) 94vw, 48vw"`:""} width="1600" height="1067" alt="${esc(p.alt)}" ${i===0&&priority?'fetchpriority="high"':'loading="lazy"'} decoding="async">
      <span class="field-tag">${esc(p.place)} · Stock photo</span></div>`;}).join("")}</div>
    <figcaption class="field-caption">
      <div class="field-tabs" role="group" aria-label="Choose a photo">${slides.map(([,title],i)=>`<button type="button" aria-pressed="${!i}" data-show-go="${i}"><span>${String(i+1).padStart(2,"0")}</span>${esc(title)}<i aria-hidden="true"></i></button>`).join("")}</div>
      <div class="field-lines">${slides.map(([,,line],i)=>`<p class="field-line${i?"":" is-active"}" ${i?'aria-hidden="true"':""}>${esc(line)}</p>`).join("")}</div>
    </figcaption>
  </figure>`;
}
