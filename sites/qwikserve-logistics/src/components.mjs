import {company,nav,process,media,locations} from "./content.mjs";
export const esc = value => String(value).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");
const paths={
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
  northeast:'<path d="M6 18 18 6M6 6h12v12"/>',
  chevron:'<path d="m8 4 8 8-8 8"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  people:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-16a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5v2"/>',
  clipboard:'<path d="M8 5H5v17h14V5h-3M8 2h8v6H8zM8 12h8m-8 4h5"/>',
  hub:'<path d="m2 10 10-7 10 7v12H2zM8 22v-9h8v9M5 10h14"/>',
  scooter:'<circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="M5 18h8l4-11h3m-4 0-1-4h-3M2 12h6l2 6M5 9h4"/>',
  parcel:'<path d="m3 7 9-5 9 5v10l-9 5-9-5zM3 7l9 5 9-5m-9 5v10M8 4l9 5"/>',
  bolt:'<path d="m14 2-11 13h8l-1 7L21 9h-8z"/>',
  route:'<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h9a4 4 0 0 1 0 8H8a3 3 0 0 0 0 6h9"/>',
  food:'<path d="M4 2v7c0 4 5 4 5 0V2M6.5 2v20M16 2v10h5M21 22V2c-4 0-5 5-5 10"/>',
  store:'<path d="M3 10v12h18V10M2 4h20l-2 6H4zM9 22v-8h6v8"/>',
  medical:'<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>',
  pin:'<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  phone:'<path d="m4 2 5 1 1 5-3 2c2 4 4 6 8 8l2-3 5 1v5c-10 3-23-10-18-19Z"/>',
  chat:'<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/><path d="M8 10h8M8 13h5"/>',
  mail:'<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m3 6 9 7 9-7"/>',
  wallet:'<path d="M20 7V3H5a3 3 0 0 0 0 6h17v12H5a3 3 0 0 1-3-3V6M16 13h6v4h-6z"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  play:'<path d="m9 5 11 7-11 7z"/>',
  chart:'<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
  shield:'<path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>',
  leaf:'<path d="M5 21c0-9 5-15 16-16-1 11-7 16-16 16Z"/><path d="M5 21 14 12"/>',
  copy:'<rect x="8" y="8" width="13" height="14" rx="2"/><path d="M16 8V2H2v14h6"/>',
};
export function icon(name,cls=""){return '<svg class="icon '+cls+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name]||paths.arrow)+'</svg>';}
const socialPaths={
 whatsapp:'<path fill="currentColor" d="M12 2.2a9.7 9.7 0 0 0-8.3 14.8L2.4 21.8l4.9-1.3A9.7 9.7 0 1 0 12 2.2zm0 17.7a8 8 0 0 1-4.1-1.1l-.3-.2-2.9.8.8-2.8-.2-.3A8 8 0 1 1 12 19.9z"/><path fill="currentColor" d="M16.4 14.1c-.2-.1-1.4-.7-1.6-.8s-.4-.1-.5.1-.6.8-.8 1-.3.2-.5.1a6.5 6.5 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.7-1.8c-.2-.5-.4-.4-.5-.4h-.5a.9.9 0 0 0-.7.3 2.8 2.8 0 0 0-.9 2.1 4.9 4.9 0 0 0 1 2.6 11.2 11.2 0 0 0 4.3 3.8c1.6.7 2.2.7 3 .6a2.6 2.6 0 0 0 1.7-1.2 2.1 2.1 0 0 0 .2-1.2c-.1-.1-.2-.2-.4-.3z"/>',
 instagram:'<rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="1.9"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="1.9"/><circle cx="17.4" cy="6.6" r="1.2" fill="currentColor"/>',
 linkedin:'<path fill="currentColor" d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.5h4v11H3zm7 0h3.8v1.6h.1a4.2 4.2 0 0 1 3.8-2c4 0 4.8 2.6 4.8 6.1v5.3h-4v-4.7c0-1.1 0-2.6-1.6-2.6s-1.8 1.2-1.8 2.5v4.8h-4z"/>'};
export const socialLinks=()=>'<div class="social-links">'+[["whatsapp","WhatsApp",company.whatsapp.href],["instagram","Instagram",company.instagram],["linkedin","LinkedIn",company.linkedin]].map(([k,l,h])=>'<a href="'+h+'" target="_blank" rel="noopener" aria-label="Qwikserve on '+l+'" title="'+l+'"><svg viewBox="0 0 24 24" aria-hidden="true">'+socialPaths[k]+'</svg></a>').join('')+'</div>';
export const callButton=(label="Call us",style="call")=>'<a class="button '+style+' call-button" href="'+company.phones[0].href+'" aria-label="Call Qwikserve">'+icon("phone")+'<span>'+label+'</span></a>';
export const eyebrow=(text)=>'<p class="eyebrow"><span aria-hidden="true"></span>'+text+'</p>';
export const button=(text,href,style="primary",extra="")=>'<a class="button '+style+'" href="'+href+'" '+extra+'>'+text+icon("arrow")+'</a>';
export const link=(text,href)=>'<a class="text-link" href="'+href+'">'+text+icon("arrow")+'</a>';
export const brand=()=>'<a class="brand" href="/" aria-label="Qwikserve Logistics Services home"><img src="/assets/mark.png" width="48" height="24" alt=""><span>Qwikserve<small>LOGISTICS SERVICES</small><small class="brand-tag">Delivering Trust, Delivering Happiness</small></span></a>';
export function header(current){
 return '<a class="skip-link" href="#main">Skip to content</a><header class="header"><div class="header-inner">'+brand()+'<nav aria-label="Main navigation">'+nav.map(([url,title])=>'<a href="'+url+'" '+(current===url?'aria-current="page"':'')+'>'+title+'</a>').join('')+'</nav><div class="header-actions"><a class="support-link" href="/rider-support/" '+(current==="/rider-support/"?'aria-current="page"':'')+'>Rider support</a>'+button("Partner with us","/partners/#enquire","primary button-small")+'<details class="mobile-menu"><summary aria-label="Open navigation menu">'+icon("menu")+'</summary><div class="mobile-nav" role="navigation" aria-label="Mobile navigation"><a class="mobile-primary" href="/partners/#enquire">Partner with us →</a>'+nav.map(([url,t])=>'<a href="'+url+'" '+(current===url?'aria-current="page"':'')+'>'+t+'</a>').join('')+'<a href="/rider-support/">Rider support</a><a href="/contact/">Contact</a></div></details></div></div></header>';
}
export function footer(){return '<footer class="footer"><div class="container footer-main"><div class="footer-brand">'+brand()+'<p class="footer-line">The right riders, on every shift.</p><span>Delivery manpower, since 2019.</span></div><div><h2>For your business</h2><a href="/partners/">Partner with Qwikserve</a><a href="/partners/#services">Our services</a><a href="/partners/#coverage">Operating locations</a><a href="/highlights/">Experience & highlights</a></div><div><h2>For our people</h2><a href="/join/">Join as a rider</a><a href="/rider-support/">Rider support</a><a href="/about/">About Qwikserve</a><a href="/contact/">Contact us</a></div><div class="footer-contact"><h2>Let’s talk</h2><p class="footer-address">'+company.address+'</p><a href="mailto:'+company.email+'">'+company.email+'</a>'+callButton("Call us","call call-small")+socialLinks()+'</div></div><div class="container footer-bottom"><span>© '+new Date().getFullYear()+' '+company.name+'</span><div><a href="/privacy/">Privacy</a><a href="/terms/">Website terms</a><a href="#top">Back to top ↑</a></div></div></footer>';}
export function sectionTitle(label,title,desc="",center=false){return '<div class="section-heading '+(center?'centered':'')+'"><div>'+eyebrow(label)+'<h2>'+title+'</h2></div>'+(desc?'<p>'+desc+'</p>':'')+'</div>';}
export function cta(title="A good shift starts<br>with the right team.",text="Tell us where you need riders. We’ll take it from there.",label="Share your requirement",href="/partners/#enquire",kicker="LET’S GET TO WORK"){return '<section class="closing"><div class="container closing-grid"><div>'+eyebrow(kicker)+'<h2>'+title+'</h2><p>'+text+'</p></div>'+button(label,href,"white")+'<div class="closing-route" aria-hidden="true"><i></i><i></i><i></i></div></div></section>';}
export function faq(items,label="Your questions, answered.",intro="A little clarity before the next step."){
 return '<section class="section container faq-section">'+sectionTitle("GOOD TO KNOW",label,intro)+'<div class="faq-list">'+items.map(([q,a])=>'<details><summary>'+q+icon("plus")+'</summary><div><p>'+a+'</p></div></details>').join('')+'</div></section>';
}
export const image=(name,alt,cls="",priority=false)=>{
 const slot=Object.values(media).find(m=>m.illustration==="/assets/"+name);
 const source=slot?.photo||"/assets/"+name;
 const description=slot?.photo?slot.photoAlt:alt;
 return '<img class="'+cls+(slot?.photo?' operations-photo':'')+'" src="'+esc(source)+'" alt="'+esc(description||alt)+'" width="800" height="600" '+(priority?'fetchpriority="high"':'loading="lazy"')+'>';
};
export function pageHero(kicker,title,desc,art,alt,action,href){return '<section class="inner-hero container"><div class="inner-hero-copy">'+eyebrow(kicker)+'<h1>'+title+'</h1><p>'+desc+'</p>'+button(action,href)+'</div><div class="inner-hero-art" data-reveal>'+image(art,alt,"",true)+'<span class="art-caption">People. Process. Possibility.</span></div></section>';}
export function steps(simple=false){return '<ol class="step-grid '+(simple?'simple':'')+'">'+process.map((p,i)=>'<li data-reveal><span class="step-number">0'+(i+1)+'</span>'+icon(p.icon)+'<h3>'+p.name+'</h3><p>'+p.body+'</p></li>').join('')+'</ol>';}
export function coverage(){return '<div class="coverage-layout"><div class="location-grid">'+locations.map(([title,tag,body],i)=>'<article data-reveal><div class="location-mark">'+icon("pin")+'<span>0'+(i+1)+'</span></div><h3>'+title+'</h3><strong>'+tag+'</strong><p>'+body+'</p></article>').join('')+'</div></div>';}
export function processBoard(){
return '<h2 class="sr-only">How Qwikserve works</h2><div class="process-explorer" data-process><div class="process-tabs" role="tablist" aria-label="How we work">'+process.map((p,i)=>'<button type="button" role="tab" id="step-tab-'+i+'" aria-controls="step-panel-'+i+'" aria-selected="'+(!i)+'" tabindex="'+(i?-1:0)+'" data-step="'+i+'"><span>0'+(i+1)+'</span>'+p.name+'</button>').join('')+'</div><div class="process-stage">'+process.map((p,i)=>'<div class="process-panel" id="step-panel-'+i+'" role="tabpanel" aria-labelledby="step-tab-'+i+'" '+(i?'hidden':'')+'><div class="process-copy"><span class="small-label">'+p.tag+'</span><h3>'+p.title+'</h3><p>'+p.body+'</p>'+link("Explore the partnership","/partners/#process")+'</div><div class="process-picture">'+image(i===0||i===3?"hub-operations.svg":i===1?"recruitment-desk.svg":"rider-journey.svg?v=12","Illustration of "+p.name.toLowerCase(),"",i===0)+'<div class="stage-stamp">'+icon("check")+'<span>'+["Your requirement comes first","A conversation, then a plan","People ready for the next step","Support beyond onboarding"][i]+'</span></div></div></div>').join('')+'</div><noscript><ol>'+process.map(p=>'<li><b>'+p.name+'</b> '+p.body+'</li>').join('')+'</ol></noscript></div>';
}
export function filmSlot(){const m=media.operations;if(!m.video)return '<div class="film-fallback"><div>'+eyebrow("A CLOSER LOOK")+'<h3>The work behind<br>the workforce.</h3><p>Recruitment on the ground. Coordination at the desk. Support through the assignment.</p>'+link("Meet the team behind it","/about/#team")+'</div>'+image("recruitment-desk.svg","Illustration of the recruitment and coordination process")+'</div>';return '<button class="film-poster" data-video="'+esc(m.video)+'" data-captions="'+esc(m.captions||"")+'" data-transcript="'+esc(m.transcript||"")+'" aria-label="Play Qwikserve operations film"><img src="'+esc(m.poster||m.illustration)+'" alt="Qwikserve operations film">'+icon("play")+'<span>Watch our operations film</span></button>';}
export const note=(content)=>'<p class="note">'+icon("check")+'<span>'+content+'</span></p>';
export function shell(page){
const canonical=company.origin+page.path;
return '<!doctype html><html lang="en-IN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#ffffff"><title>'+esc(page.title)+' | Qwikserve Logistics</title><meta name="description" content="'+esc(page.description)+'"><link rel="canonical" href="'+canonical+'"><meta property="og:title" content="'+esc(page.title)+' | Qwikserve"><meta property="og:description" content="'+esc(page.description)+'"><meta property="og:type" content="website"><meta property="og:url" content="'+canonical+'"><meta property="og:image" content="'+company.origin+'/assets/social-card.png"><link rel="icon" href="/assets/mark.png"><link rel="preload" href="/assets/archivo_extrabold.ttf" as="font" type="font/ttf" crossorigin><link rel="stylesheet" href="/styles.css?v=6"><link rel="stylesheet" href="/revision.css?v=15"><link rel="stylesheet" href="/journey.css?v=18"><link rel="stylesheet" href="/polish.css?v=5"><script>document.documentElement.classList.add("js-reveal")</script><script type="module" src="/app.js?v=16"></script></head><body id="top" class="page-'+page.key+'">'+header(page.path)+'<main id="main">'+page.content+'</main>'+footer()+'<dialog id="video-dialog" aria-label="Qwikserve operations film"><button class="dialog-close" type="button" aria-label="Close video">'+icon("plus")+'</button><video controls playsinline preload="none"></video><p class="video-transcript"></p><p class="video-error" hidden>We couldn’t load this film. Please read the description or contact our team.</p></dialog></body></html>';
}

