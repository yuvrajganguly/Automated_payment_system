import {createServer} from "node:http";
import {readFile,stat} from "node:fs/promises";
import {resolve,extname,sep,dirname} from "node:path";
import {fileURLToPath} from "node:url";
const root=resolve(dirname(fileURLToPath(import.meta.url)),"../out");
const types={".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"text/javascript; charset=utf-8",".mjs":"text/javascript; charset=utf-8",".svg":"image/svg+xml",".png":"image/png",".jpg":"image/jpeg",".webp":"image/webp",".ttf":"font/ttf",".woff2":"font/woff2",".webm":"video/webm",".xml":"application/xml",".txt":"text/plain; charset=utf-8",".mp4":"video/mp4",".vtt":"text/vtt"};
const port=Number(process.env.PORT||4784);
createServer(async(req,res)=>{
 try{
   const pathname=decodeURIComponent(new URL(req.url,"http://localhost").pathname);
   let file=resolve(root,"."+pathname);
   if(file!==root&&!file.startsWith(root+sep)){res.writeHead(403);res.end();return;}
   try{
     if((await stat(file)).isDirectory()){
       if(!pathname.endsWith("/")){res.writeHead(302,{Location:pathname+"/"+new URL(req.url,"http://localhost").search});res.end();return;}
       file=resolve(file,"index.html");
     }
     const body=await readFile(file);
     res.writeHead(200,{"Content-Type":types[extname(file)]||"application/octet-stream","Cache-Control":"no-store"});
     res.end(req.method==="HEAD"?undefined:body);
   }catch{
     res.writeHead(404,{"Content-Type":"text/html; charset=utf-8"});res.end(await readFile(resolve(root,"404.html")));
   }
 }catch{res.writeHead(400);res.end("Bad request");}
}).listen(port,"127.0.0.1",()=>console.log("Qwikserve preview: http://127.0.0.1:"+port));

