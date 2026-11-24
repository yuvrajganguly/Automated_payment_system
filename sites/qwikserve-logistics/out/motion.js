// Rails use a second, inaccessible copy to cross the seam without resetting focus.
const motion = matchMedia("(prefers-reduced-motion: reduce)");
function fallbackPortrait(img){
  const replacement=document.createElement("span");replacement.className="rider-avatar";
  replacement.setAttribute("aria-hidden","true");replacement.textContent=img.dataset.initials;img.replaceWith(replacement);
}
document.querySelectorAll("img[data-initials]").forEach(img=>{
  img.addEventListener("error",()=>fallbackPortrait(img),{once:true});
  if(img.complete && !img.naturalWidth)fallbackPortrait(img);
});
document.addEventListener("error",e=>{if(e.target.matches?.("img[data-initials]"))fallbackPortrait(e.target);},true);

document.querySelectorAll("[data-rail]").forEach(rail => {
  const frame=rail.querySelector(".rail-window"), list=rail.querySelector(".rail-group");
  const controls=rail.querySelector(".rail-controls"), toggle=rail.querySelector("[data-rail-toggle]");
  if(list.children.length < 2) return;
  const duplicate=list.cloneNode(true);
  duplicate.setAttribute("aria-hidden","true"); duplicate.inert=true;
  duplicate.querySelectorAll("img").forEach(img=>img.alt="");
  list.after(duplicate);
  let width=0, x=0, paused=false, over=false, focused=false, visible=false, id=0, last=0;
  const speed=Number(rail.dataset.speed), manual=!!rail.querySelector("[data-rail-next]");
  rail.classList.toggle("manual-rail",manual);
  function measure(){width=list.getBoundingClientRect().width; x=frame.scrollLeft; update();}
  function tick(now){
    if (!id) return;
    if(last && width){x=(x+Math.min(now-last,64)*speed/1000)%width;frame.scrollLeft=x;}
    last=now;id=requestAnimationFrame(tick);
  }
  function update(){
    controls.hidden=(motion.matches && !manual) || width<=frame.clientWidth;
    toggle.hidden=motion.matches;duplicate.hidden=controls.hidden || motion.matches;
    toggle.textContent=paused?"Play":"Pause";
    toggle.setAttribute("aria-label",paused?"Resume scrolling":"Pause scrolling");
    const run=!motion.matches && !controls.hidden && visible && !over && !focused && !paused && !document.hidden;
    frame.toggleAttribute("data-running",run);
    if(run && !id){last=0;x=frame.scrollLeft;id=requestAnimationFrame(tick);}
    if(!run && id){cancelAnimationFrame(id);id=0;}
  }
  function step(dir){
    paused=true;update();
    const nodes=[...list.children];
    const offsets=nodes.map(n=>n.getBoundingClientRect().left-list.getBoundingClientRect().left);
    const pos=frame.scrollLeft%width;
    if(motion.matches && dir>0 && frame.scrollLeft>=frame.scrollWidth-frame.clientWidth-2){frame.scrollLeft=0;return;}
    frame.scrollLeft=dir>0?(offsets.find(o=>o>pos+2)??0):([...offsets].reverse().find(o=>o<pos-2)??offsets.at(-1));
  }
  toggle.addEventListener("click",()=>{paused=!paused;update();});
  rail.querySelector("[data-rail-prev]")?.addEventListener("click",()=>step(-1));
  rail.querySelector("[data-rail-next]")?.addEventListener("click",()=>step(1));
  frame.addEventListener("pointerenter",e=>{over=e.pointerType==="mouse";update();});
  frame.addEventListener("pointerleave",()=>{over=false;update();});
  frame.addEventListener("pointerdown",()=>{paused=true;update();});
  frame.addEventListener("focusin",()=>{focused=true;update();});
  frame.addEventListener("focusout",()=>{focused=false;update();});
  document.addEventListener("visibilitychange",update);motion.addEventListener("change",measure);
  new ResizeObserver(measure).observe(frame);
  new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;update();}).observe(rail);
  measure();
});

document.querySelectorAll("[data-guide]").forEach(guide=>{
  const buttons=[...guide.querySelectorAll("[data-stage]")];
  const photos=[...guide.querySelectorAll(".guide-image")];
  const prev=guide.querySelector("[data-guide-prev]"), next=guide.querySelector("[data-guide-next]");
  const small=matchMedia("(max-width:700px)");let active=-1;
  function select(index, focus=false){
    const i=Math.min(buttons.length-1,Math.max(0,index));
    if(i===active)return;
    active=i;
    guide.querySelectorAll(".journey-progress i").forEach((bar,n)=>bar.classList.toggle("filled",n<=i));
    buttons.forEach((b,n)=>{
      b.setAttribute("aria-pressed",String(n===i));b.parentNode.classList.toggle("current",n===i);
      photos[n].setAttribute("aria-hidden",String(n!==i));photos[n].classList.toggle("active",n===i);
    });
    prev.disabled=i===0;next.disabled=i===buttons.length-1;
    guide.querySelector("[data-guide-position]").textContent="Step "+(i+1)+" of "+buttons.length;
    if(focus)buttons[i].focus({preventScroll:true});
  }
  buttons.forEach((b,i)=>{
    b.addEventListener("click",()=>select(i));
    b.addEventListener("keydown",e=>{
      const target={ArrowLeft:i-1,ArrowUp:i-1,ArrowRight:i+1,ArrowDown:i+1,Home:0,End:buttons.length-1}[e.key];
      if(target!==undefined){e.preventDefault();select(target,true);}
    });
  });
  prev.addEventListener("click",()=>select(active-1));next.addEventListener("click",()=>select(active+1));
  const picture=guide.querySelector(".guide-pictures");let touch;
  picture.addEventListener("touchstart",e=>{touch=e.touches[0];},{passive:true});
  picture.addEventListener("touchend",e=>{if(!touch)return;const t=e.changedTouches[0],dx=t.clientX-touch.clientX,dy=t.clientY-touch.clientY;
    if(Math.abs(dx)>45 && Math.abs(dx)>Math.abs(dy)*1.4)select(active+(dx<0?1:-1));touch=null;},{passive:true});
  let scheduled=false;
  window.addEventListener("scroll",()=>{
    if(scheduled || small.matches || guide.contains(document.activeElement))return;
    scheduled=true;requestAnimationFrame(()=>{
      scheduled=false;
      const y=Math.max(120,window.innerHeight*.38),box=guide.getBoundingClientRect();
      if(box.top>y || box.bottom<y)return;
      const index=buttons.findLastIndex(b=>b.getBoundingClientRect().top<y);
      select(Math.max(0,index));
    });
  },{passive:true});
  select(0);guide.classList.add("enhanced");guide.querySelector(".guide-navigation").hidden=false;
});
const header=document.querySelector(".header");
const paintHeader=()=>header?.classList.toggle("is-scrolled",window.scrollY>8);
window.addEventListener("scroll",paintHeader,{passive:true});paintHeader();



document.querySelectorAll("video[data-loop-src]").forEach(clip => {
  const frame = clip.closest(".short-film");
  const control = frame.querySelector(".pause-film");
  const connection = navigator.connection;
  let visible = false;
  let choice = "auto";
  let failed = false;

  function updateControl() {
    const playing = !clip.paused;
    control.hidden = failed || !visible;
    control.setAttribute("aria-label", playing ? "Pause film" : "Play film");
    control.title = playing ? "Pause film" : "Play film";
    control.classList.toggle("is-playing", playing);
  }

  function updatePlayback() {
    const shouldPlay = visible && !document.hidden && !failed &&
      (choice === "play" || (choice === "auto" && !motion.matches && !connection?.saveData));
    if (!shouldPlay) {
      clip.pause();
      updateControl();
      return;
    }
    if (!clip.hasAttribute("src")) clip.src = clip.dataset.loopSrc;
    clip.play().catch(error => {
      if (error.name === "NotAllowedError") choice = "pause";
      updateControl();
    });
  }

  control.addEventListener("click", () => {
    choice = clip.paused ? "play" : "pause";
    updatePlayback();
  });
  clip.addEventListener("playing", () => {
    frame.classList.add("has-video");
    updateControl();
  });
  clip.addEventListener("pause", updateControl);
  clip.addEventListener("error", () => {
    failed = true;
    frame.classList.remove("has-video");
    updateControl();
  });
  motion.addEventListener("change", () => { choice = "auto"; updatePlayback(); });
  connection?.addEventListener("change", updatePlayback);
  document.addEventListener("visibilitychange", updatePlayback);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    updateControl();
    updatePlayback();
  }, {threshold: 0.12}).observe(frame);
});

// Rider-journey slideshows: crossfade with a slow drift, a progress bar per
// slide, autoplay only while in view, pause on hover/focus, swipe on touch.
document.querySelectorAll("[data-slideshow]").forEach(show => {
  const slides = [...show.querySelectorAll(".journey-slide")];
  const caps = [...show.querySelectorAll(".journey-cap")];
  const bars = [...show.querySelectorAll(".journey-progress-bar i")];
  const toggle = show.querySelector("[data-show-toggle]");
  const DURATION = 5200;
  let index = 0, timer = 0, started = 0, left = DURATION, visible = false, hovered = false, paused = motion.matches;
  show.style.setProperty("--show-duration", DURATION + "ms");
  function go(next) {
    index = (next + slides.length) % slides.length;
    slides.forEach((s, i) => { s.classList.toggle("is-active", i === index); s.setAttribute("aria-hidden", String(i !== index)); });
    caps.forEach((c, i) => { c.classList.toggle("is-active", i === index); c.setAttribute("aria-hidden", String(i !== index)); });
    bars.forEach((b, i) => { b.classList.toggle("done", i < index); b.classList.remove("running"); void b.offsetWidth; });
    const img = slides[index].querySelector("img"); if (img.loading === "lazy") img.loading = "eager";
    const after = slides[(index + 1) % slides.length].querySelector("img"); if (after.loading === "lazy") after.loading = "eager";
    left = DURATION; schedule();
  }
  function schedule() {
    clearTimeout(timer); timer = 0;
    const run = visible && !hovered && !paused && !document.hidden;
    show.classList.toggle("is-playing", run);
    toggle.classList.toggle("is-playing", !paused);
    toggle.setAttribute("aria-label", paused ? "Play slideshow" : "Pause slideshow");
    bars[index].classList.toggle("running", run);
    if (run) { started = performance.now(); timer = setTimeout(() => go(index + 1), left); }
  }
  function hold() { if (timer) { left = Math.max(400, left - (performance.now() - started)); } }
  show.querySelector("[data-show-next]").addEventListener("click", () => go(index + 1));
  show.querySelector("[data-show-prev]").addEventListener("click", () => go(index - 1));
  toggle.addEventListener("click", () => { hold(); paused = !paused; schedule(); });
  show.addEventListener("pointerenter", e => { if (e.pointerType === "mouse") { hold(); hovered = true; schedule(); } });
  show.addEventListener("pointerleave", () => { hovered = false; schedule(); });
  show.addEventListener("focusin", () => { hold(); hovered = true; schedule(); });
  show.addEventListener("focusout", () => { hovered = false; schedule(); });
  show.addEventListener("keydown", e => { if (e.key === "ArrowRight") go(index + 1); if (e.key === "ArrowLeft") go(index - 1); });
  let touch;
  show.addEventListener("touchstart", e => { touch = e.touches[0]; }, {passive:true});
  show.addEventListener("touchend", e => { if (!touch) return; const dx = e.changedTouches[0].clientX - touch.clientX; if (Math.abs(dx) > 45) go(index + (dx < 0 ? 1 : -1)); touch = null; }, {passive:true});
  document.addEventListener("visibilitychange", () => { hold(); schedule(); });
  new IntersectionObserver(([entry]) => { if (!entry.isIntersecting) hold(); visible = entry.isIntersecting; schedule(); }, {threshold:.35}).observe(show);
  show.classList.add("enhanced"); go(0);
});
