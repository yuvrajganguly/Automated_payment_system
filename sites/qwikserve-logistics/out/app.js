import "./motion.js?v=2";
import { prepareEnquiry, ENQUIRY_ENDPOINT } from "./form-model.js?v=5";
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const event = (name, detail = {}) => document.dispatchEvent(new CustomEvent("qwikserve:" + name, {detail}));
function activateTab(tab, focus = false) {
  const group = tab.closest('[role="tablist"]');
  group.querySelectorAll('[role="tab"]').forEach(other => {
    const selected = other === tab;
    other.setAttribute("aria-selected", String(selected));
    other.tabIndex = selected ? 0 : -1;
    const panel = document.getElementById(other.getAttribute("aria-controls"));
    if (panel) { panel.hidden = !selected; panel.classList.toggle("panel-active", selected); }
  });
  if (focus) tab.focus();
}
document.querySelectorAll('[role="tablist"]').forEach(group => {
  const tabs = [...group.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => {activateTab(tab); event("panel", {id: tab.id});});
    tab.addEventListener("keydown", e => {
      let index = i;
      if (["ArrowRight","ArrowDown"].includes(e.key)) index = (i + 1) % tabs.length;
      else if (["ArrowLeft","ArrowUp"].includes(e.key)) index = (i + tabs.length - 1) % tabs.length;
      else if (e.key === "Home") index = 0;
      else if (e.key === "End") index = tabs.length - 1;
      else return;
      e.preventDefault(); activateTab(tabs[index], true);
    });
  });
});
const menu = document.querySelector(".mobile-menu");
if (menu) {
  menu.addEventListener("click", e => {if (e.target.closest("a")) menu.open = false;});
  document.addEventListener("click", e => {if (!menu.contains(e.target)) menu.open = false;});
  document.addEventListener("keydown", e => {if (e.key === "Escape" && menu.open) {menu.open = false; menu.querySelector("summary").focus();}});
  menu.addEventListener("toggle", () => menu.querySelector("summary").setAttribute("aria-label",menu.open?"Close navigation menu":"Open navigation menu"));
}
const query = new URLSearchParams(location.search);
document.querySelectorAll("[data-enquiry]").forEach(form => {
  const kind = form.dataset.enquiry;
  const body = form.querySelector(".form-body");
  const success = form.querySelector(".form-success");
  const fallback = form.querySelector(".form-fallback");
  const summary = form.querySelector(".form-error");
  const status = form.querySelector(".copy-status");
  const submit = form.querySelector(".form-submit");
  const field = name => form.elements.namedItem(name);
  if(kind === "partner"){
    const sector=query.get("sector");
    if(sector && sector.length<80) {field("service").value="Multi-sector recruitment";field("brief").value="Industry: "+sector+"\n";}
  }
  if(kind === "support"){
    const topics={assignment:"Assignment & onboarding",hub:"Hub & work coordination",vehicle:"Vehicle & rental support",earnings:"Earnings & payment queries"};
    const topic=query.get("topic");
    if(topics[topic]) {field("topic").value=topics[topic];activateTab(document.getElementById("help-tab-"+Object.keys(topics).indexOf(topic)));}
  }
  function clearErrors(){
    form.querySelectorAll("[aria-invalid]").forEach(el=>el.removeAttribute("aria-invalid"));
    form.querySelectorAll(".field-error").forEach(el=>el.textContent="");
    summary.textContent="";
  }
  function show(panel){
    body.hidden = panel !== body;
    success.hidden = panel !== success;
    fallback.hidden = panel !== fallback;
    if(panel !== body){
      panel.focus({preventScroll:true});
      form.scrollIntoView({behavior:reduced.matches?"instant":"smooth",block:"start"});
    }
  }
  function busy(on){
    submit.disabled=on;submit.classList.toggle("is-busy",on);
    submit.querySelector(".submit-label").dataset.label ||= submit.querySelector(".submit-label").textContent;
    submit.querySelector(".submit-label").textContent=on?"Sending…":submit.querySelector(".submit-label").dataset.label;
  }
  form.addEventListener("input",e=>{
    const el=e.target;
    el.removeAttribute("aria-invalid");
    const error=document.getElementById(el.name+"-error");
    if(error)error.textContent="";
    summary.textContent="";
  });
  form.addEventListener("submit",async e=>{
    e.preventDefault();clearErrors();
    const data=Object.fromEntries(new FormData(form));
    const honey=data._honey;delete data._honey;
    const prepared=prepareEnquiry(kind,data);
    if(!prepared.ok){
      let first;
      for(const [name,message] of Object.entries(prepared.errors)){
        const el=field(name);
        if(!el)continue;
        el.setAttribute("aria-invalid","true");
        document.getElementById(name+"-error").textContent=message;
        first ||= el;
      }
      summary.textContent="Please check the highlighted fields.";
      first?.focus();return;
    }
    form.querySelectorAll(".draft-whatsapp").forEach(a=>{if(prepared.whatsapp)a.href=prepared.whatsapp;});
    form.querySelector(".draft-text").textContent=prepared.body;
    form.querySelector(".draft-open").href=prepared.href;
    form.querySelector(".draft-gmail").href=prepared.gmail;
    if(honey){show(success);return;}
    busy(true);
    try{
      const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
      const response=await fetch(ENQUIRY_ENDPOINT,{method:"POST",headers:{"Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify(prepared.payload),signal:controller.signal});
      clearTimeout(timer);
      const result=await response.json().catch(()=>({}));
      if(!response.ok || String(result.success)!=="true")throw new Error(result.message||response.status);
      show(success);event("enquiry_sent",{kind});
    }catch(error){
      status.textContent="";show(fallback);event("enquiry_fallback",{kind});
    }finally{busy(false);}
  });
  form.querySelector(".form-reset").addEventListener("click",()=>{form.reset();show(body);form.querySelector("input:not([type=hidden])")?.focus();});
  form.querySelector(".draft-copy").addEventListener("click",async()=>{
    const text=form.querySelector(".draft-text").textContent;
    try {await navigator.clipboard.writeText(text);status.textContent="Copied. Paste it into WhatsApp or an email to info@qwikserve.in.";}
    catch {
      form.querySelector(".draft-preview").open=true;
      const range=document.createRange();range.selectNodeContents(form.querySelector(".draft-text"));
      const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
      status.textContent="Select and copy the message above, then paste it into your email.";
    }
  });
});
// Sections fade in as they enter the view. The head script adds .js-reveal
// before first paint, so nothing flashes visible and then disappears.
const revealTargets=[...document.querySelectorAll("[data-reveal], main > section:not(.field-hero), main > div.container")];
if("IntersectionObserver" in window && !reduced.matches){
  const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
    if(!entry.isIntersecting)return;
    const el=entry.target;
    const siblings=el.parentElement?[...el.parentElement.children].filter(c=>c.hasAttribute("data-reveal")):[];
    const index=Math.max(0,siblings.indexOf(el));
    el.style.setProperty("--reveal-delay",Math.min(index,6)*70+"ms");
    el.classList.add("is-visible");observer.unobserve(el);
  }),{threshold:.08,rootMargin:"0px 0px -6% 0px"});
  revealTargets.forEach(el=>{el.classList.add("reveal-item");observer.observe(el);});
}else revealTargets.forEach(el=>el.classList.add("is-visible"));
document.documentElement.classList.add("reveal-ready");
const dialog=document.getElementById("video-dialog");
if(dialog){
  const video=dialog.querySelector("video");
  let trigger;
  document.querySelectorAll("[data-video]").forEach(button=>button.addEventListener("click",()=>{
    trigger=button;video.src=button.dataset.video;video.querySelectorAll("track").forEach(t=>t.remove());
    if(button.dataset.captions){const track=document.createElement("track");track.kind="captions";track.src=button.dataset.captions;track.srclang="en";track.label="English";track.default=true;video.append(track);}
    dialog.querySelector(".video-transcript").textContent=button.dataset.transcript;
    dialog.querySelector(".video-error").hidden=true;dialog.showModal();
    video.play().catch(()=>{});event("video_open");
  }));
  dialog.querySelector(".dialog-close").addEventListener("click",()=>dialog.close());
  dialog.addEventListener("close",()=>{video.pause();video.removeAttribute("src");video.load();trigger?.focus();});
  video.addEventListener("error",()=>dialog.querySelector(".video-error").hidden=false);
  dialog.addEventListener("click",e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
}
// Live rider figures from the payout system's aggregate-only endpoint. The
// build-time fallback stays on screen if the request fails or is slow.
const statsSource=document.querySelector("[data-stat-api]");
if(statsSource){
  const controller=new AbortController();setTimeout(()=>controller.abort(),6000);
  fetch(statsSource.dataset.statApi,{credentials:"omit",signal:controller.signal})
    .then(r=>r.ok?r.json():Promise.reject(r.status))
    .then(data=>{
      let updated=false;
      document.querySelectorAll("[data-stat]").forEach(el=>{
        const n=data[el.dataset.stat];
        if(Number.isInteger(n)&&n>0){el.textContent=n.toLocaleString("en-IN");updated=true;}
      });
      if(updated){
        document.querySelectorAll("[data-stat-live]").forEach(el=>{el.hidden=false;});
        document.querySelectorAll("[data-stat-note]").forEach(el=>{el.textContent="Live from our rider records.";});
      }
    })
    .catch(()=>{});
}
