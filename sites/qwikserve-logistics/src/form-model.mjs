export const EMAIL_TO = "info@qwikserve.in";
// WhatsApp number (country code, no +). Riders rarely have an email app set up.
export const WHATSAPP_TO = "916293004809";
// Enquiries are delivered to EMAIL_TO by FormSubmit (no mail app needed on the
// visitor's side). The first submission sends a one-time activation email to
// that inbox; click "Activate" in it once and every later enquiry arrives.
export const ENQUIRY_ENDPOINT = "https://formsubmit.co/ajax/" + EMAIL_TO;
export function prepareEnquiry(kind, raw) {
  if (!["partner","join","support"].includes(kind)) throw new Error("Unknown enquiry type");
  const values = Object.fromEntries(Object.entries(raw).map(([key,value]) => [key,String(value).replace(/\r\n?/g,"\n").trim()]));
  const errors = {};
  const required = kind==="partner"?["company","name","area","service","riders"]:kind==="join"?["name","phone","area","vehicle","language"]:["name","phone","area","topic"];
  for (const key of required) if(!values[key]) errors[key]="Please complete this field.";
  if(kind==="partner"&&!values.email&&!values.phone) errors.email="Add an email address or a phone number.";
  if(values.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) errors.email="Enter a valid email address.";
  if(values.phone){const digits=values.phone.replace(/\D/g,"");if(digits.length<8||digits.length>15||!/^[+\d\s().-]+$/.test(values.phone))errors.phone="Enter a phone number with 8–15 digits.";}
  if(kind==="support"&&!values.brief)errors.brief="Please briefly describe your question.";
  for(const [key,value] of Object.entries(values))if(value.length>(key==="brief"?1200:key==="phone"?25:150))errors[key]="Please shorten this field.";
  if(Object.keys(errors).length)return {ok:false,errors};
  const labels = {company:"Company",name:"Name",email:"Reply email",phone:"Phone",area:kind==="join"?"Preferred area":"Hub / reporting area",service:"Service needed",riders:"Approximate requirement",start:"Preferred start",vehicle:"Vehicle situation",language:"Preferred language",availability:"Availability",riderId:"Rider / company ID",topic:"Support topic",brief:"Details"};
  const titles={partner:"Delivery manpower enquiry",join:"Rider joining enquiry",support:"Rider support enquiry"};
  // Each value is kept in the encoded body, never interpolated into mail headers.
  const lines=["Hello Qwikserve team,","",...Object.keys(labels).filter(k=>values[k]).map(k=>labels[k]+": "+values[k]),"","Please contact me to discuss the next steps."];
  const body=lines.join("\r\n");
  const whatsapp="https://wa.me/"+WHATSAPP_TO+"?text="+encodeURIComponent(titles[kind]+"\n\n"+lines.join("\n"));
  const fields=Object.fromEntries(Object.keys(labels).filter(k=>values[k]).map(k=>[labels[k],values[k]]));
  const payload={_subject:titles[kind]+(values.company?" — "+values.company:values.name?" — "+values.name:""),_template:"table",_captcha:"false","Enquiry type":titles[kind],...fields};
  if(values.email)payload._replyto=values.email;
  return {ok:true,body,subject:titles[kind],whatsapp,payload,gmail:"https://mail.google.com/mail/?view=cm&fs=1&to="+EMAIL_TO+"&su="+encodeURIComponent(titles[kind])+"&body="+encodeURIComponent(body),href:"mailto:"+EMAIL_TO+"?subject="+encodeURIComponent(titles[kind])+"&body="+encodeURIComponent(body)};
}

