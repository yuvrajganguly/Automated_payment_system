import { WHATSAPP_TO } from "./form-model.mjs";
export const company = {
  name: "Qwikserve Logistics LLP",
  email: "info@qwikserve.in",
  phones: [{label:"+91 86979 78096",href:"tel:+918697978096"}],
  whatsapp: {label:"WhatsApp",href:"https://wa.me/"+WHATSAPP_TO},
  instagram:"https://www.instagram.com/qwik_serve/",
  linkedin:"https://www.linkedin.com/company/145432297/",
  address:"4 Ho Chi Minh Sarani, Kankaria Estate, Kolkata – 700071",
  origin:"https://qwikserve.in",
};
export const media = {
  // Replace an illustration with approved operations media, preserving its slot.
  // video must be a verified MP4 or WebM URL. A poster and captions are required.
  operations: {illustration:"/assets/hub-operations.svg",loop:"/assets/home-field-film.mp4?v=22",video:null,poster:"/assets/home-field-poster.webp?v=21",description:"A helmeted courier sets off with a red bag. A packer seals a parcel and a warehouse worker scans stock.",captions:null,transcript:""},
  riders: {loop:"/assets/rider-field-film.mp4?v=18",poster:"/assets/rider-field-poster.webp?v=18",description:"A helmeted courier adjusts his goggles, checks a phone at the handlebars and rides down a city street.",illustration:"/assets/rider-journey.svg?v=12",photo:null,photoAlt:"",alt:"Illustration of a delivery rider on a red scooter"},
  recruitment: {illustration:"/assets/recruitment-desk.svg",photo:null,photoAlt:"",alt:"Illustration of a recruitment clipboard and rider records"},
};
export const nav = [
  ["/partners/","For partners"],["/join/","Join as a rider"],["/highlights/","Highlights"],["/about/","About us"],
];
export const platforms = ["Spencer’s (Jiffy)","Myntra","DealShare","Blitz","Zomato","Shadowfax","Delhivery","Blue Dart","Nykaa"];
export const locations = [
  ["Kolkata","Head office & primary operations","Our main base for recruitment, coordination and rider support."],
];
export const process = [
  {name:"Source",title:"Find the people behind the next shift.",body:"Field recruiters and telecallers connect with prospective riders, starting with the location and operating requirement.",tag:"FIELD + TELECALLING",icon:"search"},
  {name:"Recruit",title:"Turn interest into the right conversation.",body:"The team screens prospective riders and explains the assignment, reporting area and vehicle requirements.",tag:"SCREENING + COORDINATION",icon:"people"},
  {name:"Onboard",title:"Get the details ready for day one.",body:"Recruiters coordinate documentation and onboarding requirements so the rider and hub know the next step.",tag:"DOCUMENTATION + ONBOARDING",icon:"clipboard"},
  {name:"Deploy & support",title:"Keep people connected on the ground.",body:"The team coordinates deployment and provides ongoing rider and operations support after onboarding.",tag:"DEPLOYMENT + SUPPORT",icon:"hub"},
];
export const sectors = [
  {name:"Quick commerce",title:"Ready for the rhythm of your dark store.",body:"Different pickup points have different peaks. Tell us your shift timings, reporting locations and the rider requirement for each.",chips:["Dark-store shifts","Peak-hour requirements","Recurring recruitment"],icon:"bolt"},
  {name:"E-commerce",title:"People behind every parcel run.",body:"Share the dispatch hub, delivery areas and recurring manpower needs. We can discuss recruitment and deployment around that brief.",chips:["Dispatch hubs","Route areas","Ongoing manpower"],icon:"parcel"},
  {name:"Food delivery",title:"Build your team around meal-time demand.",body:"Help the recruiter understand your pickup clusters and the hours that matter. Lunch, dinner and weekends may call for different coverage.",chips:["Pickup clusters","Meal-time peaks","Shift requirements"],icon:"food"},
  {name:"Courier & express",title:"A team for the next dispatch.",body:"Share reporting points, collection windows and the areas your operation serves. The team can assess the rider requirement with you.",chips:["Collection windows","Dispatch schedules","Reporting points"],icon:"route"},
  {name:"Retail delivery",title:"From the shop floor to the doorstep.",body:"List your stores, trading hours and delivery areas. Flag regular needs and changing requirements separately.",chips:["Store locations","Trading hours","Local routes"],icon:"store"},
  {name:"Pharmaceutical",title:"Recruitment for pharmacy delivery.",body:"Tell us the pickup points, expected shifts and any handling instructions that need to be explained during onboarding.",chips:["Pharmacy pickups","Shift timings","Handling instructions"],icon:"medical"},
  {name:"Hyperlocal",title:"Local people. Neighbourhood routes.",body:"Map your pickup points, operating area and recurring slots. We can discuss manpower for your neighbourhood and on-demand delivery needs.",chips:["Pickup points","Neighbourhoods","On-demand operations"],icon:"pin"},
  {name:"On-demand delivery",title:"People for when the orders come in.",body:"Tell us the hours and days when demand peaks and the areas you cover. Flexible coverage can be discussed with the recruiter.",chips:["Peak hours","Service areas","Flexible shifts"],icon:"clock"}
];
export const businessFaq = [
  ["Can you support more than one location?","Share each location and its rider requirement. The team can assess the operating brief and discuss local availability with you."],
  ["Can we discuss bulk or ongoing recruitment?","Yes. Bulk and ongoing manpower support are part of Qwikserve’s offering. Share the expected numbers, reporting points and intended start dates."],
  ["What if some riders need a vehicle?","Tell us how many riders may need rental support. Only riders working under Qwikserve can rent through this arrangement. A separate rental company supplies the EVs; the coordinator checks local availability and terms."],
  ["How are rates and start dates confirmed?","After understanding the location, service and manpower requirement, the team can discuss availability, onboarding and commercial terms. An enquiry does not reserve riders."],
  ["Can Qwikserve run the whole delivery operation?","Yes. Beyond supplying riders, we can manage the day-to-day operation at your hub: rosters and attendance, team leaders on the ground, rider payouts, COD reconciliation and the EV fleet, with one point of contact and regular reporting."],
  ["Which kinds of delivery operations do you work with?","Quick commerce, e-commerce, food delivery, courier and express, retail, pharmaceutical, hyperlocal and on-demand delivery. Our operating experience includes work associated with platforms such as Spencer’s (Jiffy), Myntra, DealShare, Zomato, Shadowfax and Delhivery."],
  ["Where do you operate?","Kolkata is our head office and primary operations base. Share your exact reporting point and we will discuss local availability."],
  ["Who looks after riders once they are deployed?","Operations coordinators keep your reporting point informed, while rider support and team leaders stay in touch with riders during the assignment. You have one team to call rather than several."]
];
export const riderFaq = [
  ["Can I enquire if I do not own a vehicle?","Yes. Tell the recruiter that you would like to discuss an EV rental option. Only riders working under Qwikserve can use this rental option. A separate company supplies the EVs, subject to local availability and agreed terms."],
  ["What documents should I bring?","Your recruiter will explain the documentation required for the assignment. Start with your name, contact number, area and vehicle situation; do not email identity or bank documents with your first enquiry."],
  ["Does sending my interest confirm a job?","No. The recruiter needs to discuss local openings, the assignment and onboarding with you before confirming next steps."],
  ["I already ride with Qwikserve. Where do I get help?","Use the Rider Support page for assignment, vehicle or earnings queries. You do not need to submit a new joining enquiry."],
  ["Where can I work?","Our main base is Kolkata. Tell the recruiter your preferred area and we will discuss local openings."],
  ["Who do I talk to after I join?","Your recruiter helps you get started. After that, the operations coordinator for your hub, rider support and your team leader are there for assignment, vehicle or earnings questions."]
];
export const supportTopics = [
  {id:"assignment",name:"Assignment & onboarding",icon:"clipboard",title:"Following up on your next step?",body:"Contact the team with your reporting area and the assignment or onboarding step you are asking about.",details:["Your name and contact number","Hub or reporting area","What you have already discussed with the recruiter"],prompt:"I would like help with my assignment or onboarding."},
  {id:"hub",name:"Hub & work coordination",icon:"hub",title:"Need help with your reporting point?",body:"Explain which hub or shift you are asking about and what needs clarification.",details:["Hub or company assignment","Relevant shift or date","A short explanation of the change or question"],prompt:"I would like help with hub or work coordination."},
  {id:"vehicle",name:"Vehicle & rental support",icon:"scooter",title:"A question about your vehicle?",body:"A separate rental company supplies EVs only for riders working under Qwikserve. Tell your coordinator what happened and give your vehicle reference if you have it.",details:["Your hub or area","Vehicle reference, if known","The issue and when you noticed it"],prompt:"I would like help with a vehicle or rental question."},
  {id:"earnings",name:"Earnings & payment queries",icon:"wallet",title:"Need to check a pay period?",body:"Have your company assignment and pay period ready. The team can guide the follow-up through the appropriate channel.",details:["Company assignment and hub","The pay period or payment date","A short description of your question"],prompt:"I would like help with an earnings or payment query."},
];

// Rider figures. The website reads them live from the payout system's public,
// aggregate-only endpoint (GET /api/public/rider-stats). Until that answers,
// these figures (supplied by Qwikserve, November 2026) are shown.
export const riderStats = {
  api: "https://app.qwikserve.in/api/public/rider-stats",
  fallbackTotal: 1073,
  fallbackActive: 504,
  fallbackNote: "As of November 2026.",
};
export const formatCount = n => n.toLocaleString("en-IN");

