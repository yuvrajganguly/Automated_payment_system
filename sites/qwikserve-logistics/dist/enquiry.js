const enquiry = document.querySelector("#partner-enquiry");
const draftStatus = document.querySelector("#draft-status");

enquiry.addEventListener("input", (event) => {
  event.target.setCustomValidity("");
  draftStatus.textContent = "";
});

enquiry.addEventListener("submit", (event) => {
  event.preventDefault();
  const fields = new FormData(enquiry);
  for (const [name, value] of fields) {
    if (!value.trim()) {
      const input = enquiry.elements.namedItem(name);
      input.setCustomValidity("Please enter a value.");
      input.reportValidity();
      return;
    }
  }

  const company = fields.get("company").trim();
  const hub = fields.get("hub").trim();
  const requirement = fields.get("requirement").trim();
  const subject = encodeURIComponent(`Delivery rider enquiry from ${company}`);
  const body = encodeURIComponent([
    "Hello Qwikserve team,",
    "",
    `Company: ${company}`,
    `Hub or location: ${hub}`,
    "",
    "Rider requirement:",
    requirement,
  ].join("\r\n"));

  draftStatus.textContent = "If your email app did not open, email info@qwikserve.in or call our team.";
  window.location.href = `mailto:info@qwikserve.in?subject=${subject}&body=${body}`;
});
