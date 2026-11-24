import { company, sectors, businessFaq, riderFaq } from "./content.mjs";
import { existsSync } from "node:fs";
import { icon, eyebrow, button, link, sectionTitle, cta, faq, steps, coverage } from "./components.mjs";
import { form } from "./forms.mjs";
import { homePage, scene, rail, rentalCopy, directContact, slideshow } from "./editorial.mjs";

export function evBrandNote(audience) {
  return `<a class="ev-brand-note" href="/#ev-brand"><span class="ev-badge"><i aria-hidden="true"></i>Coming soon</span><span><b>Our own EV brand is on its way.</b> ${audience==="partner"?"Electric two-wheelers built for delivery shifts, for the riders we deploy at your hubs.":"Electric scooters built for delivery shifts, for Qwikserve riders first."}</span>${icon("arrow")}</a>`;
}

const operations = [
  ["clipboard","Rosters & attendance","Daily rosters, attendance and shift coverage for every hub, with replacements arranged when a rider drops off."],
  ["people","Team leaders on the ground","Team leaders at your hubs handle rider questions during the shift, so your managers can stay on the operation."],
  ["wallet","Rider payouts","We calculate and pay riders from your order and attendance data, including incentives, deductions and holds."],
  ["shield","COD reconciliation","Cash collected on delivery is tracked rider by rider and reconciled against your records."],
  ["scooter","EV fleet management","Allocation, returns, maintenance and rent dues for every electric scooter on your routes."],
  ["chart","Reporting & one contact","Regular reports on headcount, attendance and payouts, and one coordinator who answers for all of it."],
];

function operationsSection() {
  return `<section class="section ops-section" id="operations"><div class="container">
    ${sectionTitle("BEYOND RECRUITMENT","Manage your<br><em>overall operations.</em>","Hand us the whole delivery operation, not just the headcount. We run the people side of your hubs end to end, so you can focus on your customers.")}
    <div class="ops-grid">${operations.map(([ic,h,b],i)=>`<article class="ops-card" data-reveal><span class="ops-index">0${i+1}</span><span class="ops-icon">${icon(ic)}</span><h3>${h}</h3><p>${b}</p></article>`).join("")}</div>
    <div class="ops-footer" data-reveal><p><b>One partner, one invoice.</b> Recruitment, deployment, payouts and fleet under a single team that already runs this for delivery companies across Kolkata.</p>${button("Discuss full operations","#enquire")}</div>
  </div></section>`;
}

function partnerEv() {
  return `<section class="section ev-section" id="ev"><div class="container field-notes"><div>${scene("vehicle","Electric scooter")}</div><div>
    ${eyebrow("ELECTRIC VEHICLES")}<h2>Vehicles?<br><em>Already handled.</em></h2>
    <p>Many good riders don’t own a bike. Riders working under Qwikserve can take a rented electric scooter from our rental partner, so you get a wider pool of people and no vehicle to manage.</p>
    <ul class="ev-list">
      <li>${icon("scooter")}<span><b>Own bike or rental EV.</b> Every rider reaches your hub on a working vehicle.</span></li>
      <li>${icon("route")}<span><b>Fleet handled by us.</b> Allocation, swaps, returns and maintenance are coordinated by our team.</span></li>
      <li>${icon("leaf")}<span><b>Cleaner last mile.</b> Electric scooters cut fuel and emissions on your routes.</span></li>
    </ul>
    ${evBrandNote("partner")}
  </div></div></section>`;
}

import { joiningGuide, riderStories, shortFilm } from "./journey.mjs";

function sectorPhoto(s) {
  const file = "sector-" + s.name.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "") + ".webp";
  if (!existsSync(new URL("./assets/" + file, import.meta.url))) return "";
  return `<figure class="sector-photo"><img src="/assets/${file}" width="1200" height="675" loading="lazy" alt="Stock photo for ${s.name.toLowerCase()}"><figcaption>Stock photo</figcaption></figure>`;
}

function industries() {
  return `<section id="industries" class="section industry-section"><div class="container">
    ${sectionTitle("INDUSTRIES WE SERVE","What kind of delivery<br><em>does your team handle?</em>")}
    <div class="industry-explorer"><div class="industry-tabs" role="tablist" aria-label="Delivery industries" aria-orientation="vertical">
      ${sectors.map((s,i)=>`<button role="tab" id="sector-tab-${i}" aria-controls="sector-panel-${i}" aria-selected="${!i}" tabindex="${i?-1:0}" data-sector="${i}">${icon(s.icon)}${s.name}${icon("arrow")}</button>`).join("")}
    </div><div class="industry-display">
      ${sectors.map((s,i)=>`<div role="tabpanel" id="sector-panel-${i}" aria-labelledby="sector-tab-${i}" ${i?"hidden":""}>${sectorPhoto(s)}<div class="sector-symbol">${icon(s.icon)}</div><h3>${s.title}</h3><p>${s.body}</p>
      <ul class="tags">${s.chips.map(x=>`<li>${x}</li>`).join("")}</ul>${link("Discuss this requirement","/partners/?sector="+encodeURIComponent(s.name)+"#enquire")}</div>`).join("")}
    </div></div></div></section>`;
}

function enquiry(kind) {
  const business = kind === "partner";
  return `<section id="${business?"enquire":"apply"}" class="section enquiry-section"><div class="container enquiry-grid">
    <div class="enquiry-intro">${eyebrow(business?"BUSINESS ENQUIRY":"RIDER ENQUIRY")}
    <h2>${business?"Where do you<br><em>need riders?</em>":"Where would you<br><em>like to ride?</em>"}</h2>
    <p>${business?"Share the reporting point, approximate headcount and intended start date.":"Tell the recruiter about your area, availability and vehicle situation."}</p>${directContact()}</div>${form(kind)}</div></section>`;
}

function partnersPage() {
  return `<section class="container inner-hero revised-hero"><div class="inner-hero-copy">${eyebrow("FOR PARTNER COMPANIES")}
    <h1>A delivery team<br><em>for your hubs.</em></h1><p>Opening a reporting point or recruiting for recurring shifts? Start with the people and locations your operation needs.</p>${button("Share your requirement","#enquire")}</div>${slideshow("rider","A rider’s journey with Qwikserve",true)}</section>
    <section id="services" class="section partner-scope"><div class="container field-notes"><div>${slideshow("brief","From your brief to the reporting point")}</div>
    <div>${eyebrow("RECRUITMENT & DEPLOYMENT")}<h2>From your brief<br><em>to the reporting point.</em></h2>
      <div class="scope-line" id="recruitment"><h3>Recruiting for a new hub</h3><p>Share the location, shift pattern and headcount. Field recruiters and telecallers source riders, discuss suitability and coordinate onboarding.</p></div>
      <div class="scope-line" id="ongoing"><h3>Maintaining a working team</h3><p>Bring recurring openings and bulk requirements into the same brief. We coordinate with your reporting points as staffing needs change.</p></div>
      <div class="scope-line"><h3>Running the whole operation</h3><p>Want more than riders? We can manage rosters, payouts, COD and the EV fleet for your hubs too. <a class="inline-link" href="#operations">See how</a></p></div>
    </div></div></section>
    ${operationsSection()}
    ${industries()}
    ${partnerEv()}
    <section class="section soft-section" id="process"><div class="container">${sectionTitle("HOW WE WORK","Four stages of recruitment.")}${steps()}</div></section>
    <section class="section container" id="coverage">${sectionTitle("OPERATING LOCATIONS","Where we work","Share your exact reporting point when you enquire.")}${coverage()}</section>
    ${faq(businessFaq,"Partner questions","Details to help prepare your staffing brief.")}${enquiry("partner")}`;
}

function joinPage() {
  return `${shortFilm("riders")}
    <div class="container already-rider">${icon("people")}<span>Already ride with Qwikserve?</span>${link("Find rider support","/rider-support/")}</div>
    ${joiningGuide()}
    <section class="section vehicle-band" id="ev-options"><div class="container field-notes"><div>${scene("vehicle","Electric scooter")}</div><div>
      ${eyebrow("VEHICLE OPTIONS")}<h2>No vehicle?<br><em>We’ve got you covered.</em></h2><p>You don’t need your own bike to start. Riders without a vehicle can take a rented electric scooter through our rental partner, and many of our riders already do.</p>
      <p>${rentalCopy}</p><p>If you do have your own vehicle, tell the recruiter its type and your preferred reporting area when you enquire.</p>${evBrandNote("rider")}${link("Speak to a recruiter","#apply")}</div></div></section>
    ${riderStories(rail)}${faq(riderFaq,"Before you join","Answers to common questions from prospective riders.")}${enquiry("join")}`;
}

export const pages = [
  {key:"home",path:"/",title:"Delivery riders for your operation",description:"Recruitment, onboarding and support for your delivery hubs. Discuss a staffing requirement with Qwikserve or enquire about joining as a rider.",content:homePage()},
  {key:"partners",path:"/partners/",title:"Delivery manpower for partner companies",description:"Discuss rider recruitment and ongoing staffing for your reporting locations.",content:partnersPage()},
  {key:"join",path:"/join/",title:"Join as a delivery rider",description:"Explore the steps to join Qwikserve and discuss your area and vehicle options with a recruiter.",content:joinPage()},
];

