import {test} from "node:test";
import assert from "node:assert/strict";
import {prepareEnquiry,EMAIL_TO,ENQUIRY_ENDPOINT} from "../src/form-model.mjs";
const partner={company:"Example Logistics",name:"Demo Contact",email:"demo@example.com",area:"Kolkata",service:"Rider recruitment & deployment",riders:"11–25 riders"};
const join={name:"Demo Rider",phone:"+91 90000 00000",area:"Siliguri",vehicle:"I have my own vehicle",language:"English"};
test("business enquiries need either email or phone, without requiring both",()=>{
 assert.equal(prepareEnquiry("partner",partner).ok,true);
 assert.equal(prepareEnquiry("partner",{...partner,email:"",phone:join.phone}).ok,true);
 assert.match(prepareEnquiry("partner",{...partner,email:"  ",phone:""}).errors.email,/email/);
});
test("malformed contact details and whitespace cannot pass validation",()=>{
 assert.match(prepareEnquiry("join",{...join,phone:"not-a-number"}).errors.phone,/phone/);
 assert.match(prepareEnquiry("join",{...join,phone:"123"}).errors.phone,/phone/);
 assert.ok(prepareEnquiry("partner",{...partner,email:"demo@"}).errors.email);
 assert.ok(prepareEnquiry("join",{...join,name:" "}).errors.name);
});
test("a support email needs enough context and optional rider ID stays optional",()=>{
 const support={name:join.name,phone:join.phone,area:"Kolkata",topic:"Earnings & payment queries"};
 assert.ok(prepareEnquiry("support",support).errors.brief);
 const result=prepareEnquiry("support",{...support,brief:"Please help clarify the reporting date."});
 assert.equal(result.ok,true);assert.match(result.body,/Earnings & payment queries/);
});
test("review preserves entered details but keeps body data out of mail headers",()=>{
 const payload="Demo\r\nBcc: another@example.com?subject=Changed&body=Injected";
 const result=prepareEnquiry("partner",{...partner,name:payload});
 assert.equal(result.ok,true);
 const url=new URL(result.href);
 assert.equal(url.pathname,EMAIL_TO);
 assert.deepEqual([...url.searchParams.keys()],["subject","body"]);
 assert.equal(url.searchParams.get("subject"),"Delivery manpower enquiry");
 assert.ok(url.searchParams.get("body").includes("Bcc: another@example.com"));
 assert.ok(result.href.includes("%0A"));
});
test("messages have bounded length and unsupported enquiry types fail",()=>{
 assert.ok(prepareEnquiry("join",{...join,brief:"a".repeat(1201)}).errors.brief);
 assert.throws(()=>prepareEnquiry("unknown",{}),/Unknown/);
});
test("each audience gets a distinct subject and only given fields are included",()=>{
 const result=prepareEnquiry("join",join);
 assert.equal(result.subject,"Rider joining enquiry");
 assert.match(result.body,/Preferred area: Siliguri/);
 assert.doesNotMatch(result.body,/undefined|Approximate requirement/);
});
test("every enquiry also prepares a WhatsApp message to the team number",()=>{
 const result=prepareEnquiry("join",join);
 const url=new URL(result.whatsapp);
 assert.equal(url.origin+url.pathname,"https://wa.me/916293004809");
 assert.match(url.searchParams.get("text"),/^Rider joining enquiry\n\nHello Qwikserve team,/);
 assert.match(url.searchParams.get("text"),/Preferred area: Siliguri/);
});
test("enquiries carry a labelled payload for direct delivery to the inbox",()=>{
 assert.equal(ENQUIRY_ENDPOINT,"https://formsubmit.co/ajax/"+EMAIL_TO);
 const result=prepareEnquiry("partner",partner);
 assert.equal(result.payload.Company,"Example Logistics");
 assert.equal(result.payload._replyto,"demo@example.com");
 assert.match(result.payload._subject,/^Delivery manpower enquiry — Example Logistics$/);
 assert.equal(prepareEnquiry("join",join).payload._replyto,undefined);
 assert.ok(!Object.values(result.payload).includes(undefined));
});
