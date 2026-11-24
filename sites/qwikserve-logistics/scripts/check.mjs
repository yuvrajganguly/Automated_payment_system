import {readFile,stat} from "node:fs/promises";
import {resolve,dirname} from "node:path";
import {fileURLToPath} from "node:url";
import assert from "node:assert/strict";
import {pages} from "../src/pages.mjs";
import {extraPages} from "../src/pages-extra.mjs";
const root=resolve(dirname(fileURLToPath(import.meta.url)),"../out");
const routes=[...pages,...extraPages];
const htmls=new Map();
for(const page of routes){
 const file=page.path==="/"?"index.html":page.path.endsWith(".html")?page.path.slice(1):page.path.slice(1)+"index.html";
 const html=await readFile(resolve(root,file),"utf8");htmls.set(page.path,html);
 assert.equal((html.match(/<h1[ >]/g)||[]).length,1,page.path+" needs one h1");
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
 assert.equal(new Set(ids).size,ids.length,page.path+" duplicate IDs");
 assert.ok(!/98309|info@qwik\.in|98%|24\/7|500\+ active/.test(html),page.path+" stale or unverified claim");
 assert.ok(!/<button[^>]*disabled/.test(html),page.path+" inactive control");
}
let links=0;
for(const [route,html] of htmls){
 for(const match of html.matchAll(/(?:href|src)="([^"]+)"/g)){
  const value=match[1].replaceAll("&amp;","&");
  if(!value.startsWith("/")&&!value.startsWith("#"))continue;
  const url=new URL(value,"https://example.test"+route);
  const path=url.pathname;const dest=htmls.get(path);
  if(dest){if(url.hash)assert.ok(dest.includes('id="'+decodeURIComponent(url.hash.slice(1))+'"'),route+" broken anchor "+value);}
  else {const info=await stat(resolve(root,"."+path)).catch(()=>null);assert.ok(info?.isFile(),route+" missing asset/page "+value);}
  links++;
 }
 for(const m of html.matchAll(/aria-controls="([^"]+)"/g))assert.ok(html.includes('id="'+m[1]+'"'),route+" broken tab connection");
}
const css=await readFile(resolve(root,"styles.css"),"utf8");
assert.ok(css.includes("prefers-reduced-motion"));
assert.ok(css.includes(":focus-visible"));
console.log("Verified "+routes.length+" pages, "+links+" local links/assets, headings, unique IDs, tab targets and motion/focus fallbacks.");

