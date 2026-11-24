import {mkdir,writeFile,copyFile,cp} from "node:fs/promises";
import {resolve,dirname} from "node:path";
import {fileURLToPath} from "node:url";
import {pages} from "../src/pages.mjs";
import {extraPages} from "../src/pages-extra.mjs";
import {shell} from "../src/components.mjs";
import {company,media} from "../src/content.mjs";
const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const out=resolve(root,"out");
if(out!==resolve(root,"out")||out===root)throw Error("Invalid output path");
for(const m of Object.values(media))if(m.video&&(!m.poster||!m.captions||!m.transcript))throw Error("A film needs an approved poster, captions and transcript.");
for(const m of Object.values(media))if(m.loop&&!m.poster)throw Error("A background film needs a poster.");
for(const m of Object.values(media))if(m.photo&&!m.photoAlt)throw Error("An operations photo needs an accurate photoAlt description.");
await mkdir(out,{recursive:true});
for(const page of [...pages,...extraPages]){
 const relative=page.path==="/"?"index.html":page.path.endsWith(".html")?page.path.slice(1):page.path.slice(1)+"index.html";
 const dest=resolve(out,relative);await mkdir(dirname(dest),{recursive:true});await writeFile(dest,shell(page).replace(/^[ \t]+$/gm,""));
}
for(const name of ["styles.css","revision.css","journey.css","polish.css","app.js","motion.js","form-model.mjs"])await copyFile(resolve(root,"src",name),resolve(out,name));
// Many shared hosts serve .mjs without a JavaScript MIME type, so ship the browser copy as .js
await copyFile(resolve(root,"src","form-model.mjs"),resolve(out,"form-model.js"));
await cp(resolve(root,"src/assets"),resolve(out,"assets"),{recursive:true});
const aliases={"partners.html":"/partners/","partner.html":"/partners/","riders.html":"/join/","workforce.html":"/partners/","fleet.html":"/join/#ev-options","company.html":"/about/"};
for(const [file,url] of Object.entries(aliases))await writeFile(resolve(out,file),'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+url+'"><meta name="robots" content="noindex"><title>Qwikserve — page moved</title></head><body><p>This page has moved. <a href="'+url+'">Continue to Qwikserve</a>.</p></body></html>');
await writeFile(resolve(out,"sitemap.xml"),'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+[...pages,...extraPages].filter(p=>p.key!=="404").map(p=>'<url><loc>'+company.origin+p.path+'</loc></url>').join('')+'</urlset>');
// The hosted review remains private. Change this only when public launch is approved.
await writeFile(resolve(out,"robots.txt"),"User-agent: *\nAllow: /\nSitemap: "+company.origin+"/sitemap.xml\n");
console.log("Built 7 main pages, privacy, terms and a 404 page in out/.");

