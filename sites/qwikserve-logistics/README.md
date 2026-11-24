# Qwikserve company website

A standalone static marketing site for prospective partner companies, new riders and existing riders. It does not connect to the payout service or read personnel records. The requirements, design and November revision brief live under ../../docs/website/.

## Run locally

With Node.js 20 or later: run `npm run build`, `npm test`, `npm run check`, then `npm run dev`. The preview is at http://127.0.0.1:4784. Rebuild after edits. Hosting uses only out/; dist/ and media/ are earlier prototypes.

## Content and assets

- src/content.mjs contains company facts, contact details (including the WhatsApp number), sector descriptions, FAQs and film configuration. The Home and Highlights rider figures (active riders and riders onboarded) are fetched live from the payout system's aggregate-only endpoint GET https://app.qwikserve.in/api/public/rider-stats; Until it answers, the figures in riderStats in content.mjs are shown (1,103 onboarded, 504 working, as of November 2026). Rental EVs come from a separate supplier, only for riders working under Qwikserve.
- src/editorial.mjs contains the homepage and the eleven supplied company marks. src/journey.mjs renders the two films, the four-step joining guide and the review carousel. Each scene has a large and small WebP, dimensions and descriptive alt text. The four scenes are licensed Pexels stock photos, captioned “Stock photo”: stock-rider (Duc Nguyen, photo 39948199), stock-warehouse (Tiger Lily, 4487361), stock-recruiter (RDNE Stock project, 7580835) and stock-ev-charging (panumas nikhomkhai, 37807346). When replacing one with an approved field photograph, update its caption, alt text and the note on the Terms page.
- The Join page shows a moving row of rider review cards. A card appears for each rider whose approved words are in quote in src/rider-interviews.mjs; with no quotes it falls back to photo cards.
- src/components.mjs, src/pages.mjs and src/pages-extra.mjs compose the pages; src/styles.css, src/revision.css and src/journey.css set the responsive layouts; src/polish.css (loaded last) adds the scroll-in section loading, glass surfaces, hover-only animated borders, the green accent and the styles for the operations, EV and About sections. Nunito and DM Sans are self-hosted with their OFL licenses in src/assets/.
- src/motion.js manages the logo and story strips, image transitions, reduced motion and opening loop. src/app.js handles tabs, the menu, form reviews and the optional film dialog.

## Films

The website film production brief in ../../docs/website/04-website-film-production-brief.docx includes the timed edit lists and stock footage credits for RDNE Stock project and Tiger Lily (Pexels). Both background films are labelled illustrative footage. The branded cuts preserve the original timings and carry the Qwikserve artwork on the rider’s bag and uniform.

Home uses media.operations and Join uses media.riders. Each has its own silent MP4, first-frame WebP poster and accessible description. Each loop plays when in view and pauses when the page is hidden. Reduced-motion and data-saving preferences initially show the poster with manual playback available. For an additional full-length film, supply video, captions and transcript together in the same media entry.

## Enquiries and checks

All three forms validate in the browser and then send the enquiry straight to info@qwikserve.in through FormSubmit (ENQUIRY_ENDPOINT in src/form-model.mjs), so visitors don't need a mail app. The very first submission triggers a one-time activation email to info@qwikserve.in: click Activate in it, and every later enquiry arrives as a formatted email (with Reply-To set to the visitor's email when given). If sending fails, the form offers WhatsApp (+91 62930 04809), Gmail, the email app, or copy. Calls go to +91 86979 78096; WhatsApp goes to +91 62930 04809. Nothing is written to the payment system. Tests cover validation, email address/header isolation, the FormSubmit payload and the three enquiry types. Structural checks cover ten generated pages, local links/assets, anchor targets, headings, IDs and accessible tab connections. 


## November 2026 revision

- Operations: Kolkata only (Uttar Pradesh removed everywhere). The Last-mile logistics sector card is gone.
- Partners page: new "Manage your overall operations" section (#operations) and an EV section (#ev).
- Home: "Our own EV brand is on its way" teaser (#ev-brand). The Partners and Join EV sections link to it. The brand name, specs and launch date aren't public yet, so the copy stays at "coming soon".
- About: Our story → Our founder → What we do (Manpower for delivery / Last-mile operations) → team, values, promise, mission.
- Partners slideshows (src/editorial.mjs `journeys`): ten licensed Pexels photos saved as src/assets/journey-*.webp. The full-size originals are in media/stock-originals/ (qs-<Pexels photo id>.jpg): 7580860, 11629486, 4484152, 24976284, 6994107 (rider journey) and 7581050, 28928633, 4487383, 33136687, 12203733 (brief to reporting point).
- Box branding removed: guide-ride-1 and stock-rider now use the unedited Pexels original (39948199). sector-e-commerce (4440801) and sector-retail-delivery (7363204) are new photos. The logo was retouched out of the boxes in stock-warehouse. Bags and uniforms keep the Qwikserve mark.
- The phone number is no longer printed anywhere; Call buttons dial company.phones[0].
